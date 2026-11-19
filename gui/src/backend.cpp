#include "backend.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QLocale>
#include <QProcessEnvironment>
#include <QSettings>
#include <QStandardPaths>
#include <QStringList>
#include <utility>

namespace {
constexpr int kMaxLogLines = 220;

QString tailOf(const QString &text, int maxLines)
{
    QStringList lines = text.split('\n');
    while (lines.size() > maxLines)
        lines.removeFirst();
    return lines.join('\n');
}

bool hasUsableFile(const QString &dir, const QString &file)
{
    return QFileInfo(dir + "/" + file).isFile();
}
} // namespace

Backend::Backend(QObject *parent)
    : Backend(detectFarmerDir(), detectDataDir(), parent)
{
}

Backend::Backend(const QString &farmerDir, const QString &dataDir, QObject *parent)
    : QObject(parent), m_farmerDir(farmerDir), m_dataDir(dataDir)
{
    init();
}

void Backend::init()
{
    m_process = new QProcess(this);
    m_process->setProcessChannelMode(QProcess::MergedChannels);

    connect(m_process, &QProcess::readyRead, this, [this] {
        appendRunner(QString::fromUtf8(m_process->readAll()));
    });
    connect(m_process, &QProcess::started, this, [this] {
        setStarting(true);
        refreshRunning();
    });
    connect(m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            setStarting(false);
            setError(QStringLiteral("Не удалось запустить python3 и tools/farm.py"));
            refreshRunning();
        }
    });
    connect(m_process, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished), this,
            [this](int code, QProcess::ExitStatus status) {
        setStarting(false);
        setStopping(false);
        if (code != 0 || status != QProcess::NormalExit) {
            const QStringList lines = m_runnerLog.split('\n', Qt::SkipEmptyParts);
            const QString last = lines.isEmpty() ? QString() : lines.last().trimmed();
            if (!last.isEmpty())
                setError(last);
            else
                setError(QStringLiteral("Фермер завершился с кодом %1").arg(code));
        }
        refreshStatus();
        refreshLog();
        refreshRunning();
    });

    m_timer.setInterval(1000);
    connect(&m_timer, &QTimer::timeout, this, [this] {
        refreshStatus();
        refreshLog();
    });
    m_timer.start();

    loadTargets();
    refreshStatus();
    refreshLog();
    refreshRunning();
}

QString Backend::statusPath() const
{
    return m_dataDir + "/farmer_status.json";
}

QString Backend::logPath() const
{
    return m_dataDir + "/farmer.log";
}

QString Backend::stopPath() const
{
    return m_dataDir + "/farmer_stop";
}

void Backend::loadTargets()
{
    m_characters.clear();
    m_stages.clear();

    QFile file(m_farmerDir + "/targets.json");
    if (!file.open(QIODevice::ReadOnly)) {
        setError(QStringLiteral("Не найден targets.json в %1").arg(shortenPath(m_farmerDir)));
        emit targetsChanged();
        return;
    }
    QJsonParseError error{};
    const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        setError(QStringLiteral("targets.json не читается: %1").arg(error.errorString()));
        emit targetsChanged();
        return;
    }

    const QJsonObject root = doc.object();
    const QJsonObject chars = root.value("characters").toObject();
    QStringList charOrder{QStringLiteral("sinx"), QStringLiteral("sniper"), QStringLiteral("bard"),
                          QStringLiteral("knight"), QStringLiteral("crusader"),
                          QStringLiteral("high_priest"), QStringLiteral("professor"),
                          QStringLiteral("blacksmith")};
    for (auto it = chars.begin(); it != chars.end(); ++it)
        if (!charOrder.contains(it.key()))
            charOrder.append(it.key());
    for (const QString &id : std::as_const(charOrder)) {
        if (!chars.contains(id))
            continue;
        const QJsonObject c = chars.value(id).toObject();
        QVariantMap item;
        item.insert("id", id);
        item.insert("label", c.value("label").toString(id));
        item.insert("class", c.value("class").toString());
        item.insert("job_path", c.value("job_path").toInt());
        m_characters.append(item);
    }

    const QJsonObject stages = root.value("stages").toObject();
    QStringList stageOrder;
    // The measured best run for the main SinX profile is Rachel Sanctuary
    // (ra_san|25 in the farmer's arms); keep it first so Start uses it.
    const QString preferred = QStringLiteral("ra_san");
    if (stages.contains(preferred))
        stageOrder.append(preferred);
    for (auto it = stages.begin(); it != stages.end(); ++it)
        if (it.key() != preferred)
            stageOrder.append(it.key());
    for (const QString &id : std::as_const(stageOrder)) {
        QVariantMap item;
        item.insert("id", id);
        item.insert("label", stages.value(id).toString(id));
        m_stages.append(item);
    }

    if (m_characters.isEmpty() || m_stages.isEmpty()) {
        setError(QStringLiteral("targets.json пуст: нет персонажей или локаций"));
    } else {
        setError(QString());
    }
    emit targetsChanged();
}

void Backend::refreshStatus()
{
    QFile file(statusPath());
    if (!file.open(QIODevice::ReadOnly)) {
        if (!m_status.isEmpty() || !m_phase.isEmpty()) {
            m_status.clear();
            m_phase.clear();
            emit statusChanged();
        }
        refreshRunning();
        return;
    }
    QJsonParseError error{};
    const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        refreshRunning();
        return;
    }
    m_status = doc.object().toVariantMap();
    m_phase = m_status.value("phase").toString();
    emit statusChanged();
    refreshRunning();
}

void Backend::refreshLog()
{
    QFile file(logPath());
    if (!file.open(QIODevice::ReadOnly)) {
        if (!m_logText.isEmpty()) {
            m_logText.clear();
            emit logTextChanged();
        }
        return;
    }
    const qint64 size = file.size();
    if (size > 65536)
        file.seek(size - 65536);
    const QString text = tailOf(QString::fromUtf8(file.readAll()), kMaxLogLines);
    if (text != m_logText) {
        m_logText = text;
        emit logTextChanged();
    }
    if (!m_noticeDismissed) {
        if (text.contains(QStringLiteral("CLASS_LOCKED")))
            setNotice(QStringLiteral("Класс не открыт в профиле — фермер не начал забег."));
        else if (text.contains(QStringLiteral("STAGE_LOCKED")))
            setNotice(QStringLiteral("Локация ещё не открыта — выберите другую."));
    }
}

void Backend::refreshRunning()
{
    const bool processRunning = m_process && m_process->state() != QProcess::NotRunning;
    const bool running = processRunning || statusActive();
    if (running != m_running) {
        m_running = running;
        emit runningChanged();
    }
    if (!running && m_stopping)
        setStopping(false);
    updateBusy();
}

bool Backend::statusActive() const
{
    if (m_phase.isEmpty())
        return false;
    const bool activePhase = m_phase == QStringLiteral("boot") || m_phase == QStringLiteral("run")
                          || m_phase == QStringLiteral("settle") || m_phase == QStringLiteral("keep")
                          || m_phase == QStringLiteral("maint");
    if (!activePhase)
        return false;
    const qint64 heartbeat = m_status.value("heartbeat").toLongLong();
    if (heartbeat <= 0)
        return false;
    return qAbs(QDateTime::currentSecsSinceEpoch() - heartbeat) <= 12;
}

void Backend::updateBusy()
{
    const bool busy = m_running || m_starting;
    if (busy != m_busy) {
        m_busy = busy;
        emit busyChanged();
    }
}

void Backend::setStarting(bool value)
{
    if (m_starting == value)
        return;
    m_starting = value;
    emit startingChanged();
    updateBusy();
}

void Backend::setStopping(bool value)
{
    if (m_stopping == value)
        return;
    m_stopping = value;
    emit stoppingChanged();
}

void Backend::setError(const QString &text)
{
    if (m_error == text)
        return;
    m_error = text;
    emit errorChanged();
}

void Backend::setNotice(const QString &text)
{
    if (m_notice == text)
        return;
    m_notice = text;
    emit noticeChanged();
}

void Backend::clearError()
{
    setError(QString());
}

void Backend::clearNotice()
{
    m_noticeDismissed = true;
    setNotice(QString());
}

void Backend::appendRunner(const QString &text)
{
    if (text.isEmpty())
        return;
    m_runnerLog.append(text);
    m_runnerLog = tailOf(m_runnerLog, kMaxLogLines);
    emit runnerLogChanged();
    if (!m_noticeDismissed) {
        if (m_runnerLog.contains(QStringLiteral("CLASS_LOCKED")))
            setNotice(QStringLiteral("Класс не открыт в профиле — фермер не начал забег."));
        else if (m_runnerLog.contains(QStringLiteral("STAGE_LOCKED")))
            setNotice(QStringLiteral("Локация ещё не открыта — выберите другую."));
    }
}

QStringList Backend::farmArguments(const QString &character, const QString &stage, int danger) const
{
    return {QStringLiteral("--char"), character, QStringLiteral("--stage"), stage,
            QStringLiteral("--danger"), QString::number(danger)};
}

bool Backend::startRun(const QString &character, const QString &stage, int danger)
{
    if (m_busy) {
        setError(QStringLiteral("Ферма уже запущена — сначала остановите её."));
        return false;
    }
    bool knownCharacter = false;
    for (const QVariant &entry : std::as_const(m_characters)) {
        if (entry.toMap().value("id").toString() == character) {
            knownCharacter = true;
            break;
        }
    }
    bool knownStage = false;
    for (const QVariant &entry : std::as_const(m_stages)) {
        if (entry.toMap().value("id").toString() == stage) {
            knownStage = true;
            break;
        }
    }
    if (!knownCharacter || !knownStage) {
        setError(QStringLiteral("Выберите персонажа и локацию."));
        return false;
    }
    if (!hasUsableFile(m_farmerDir, "tools/farm.py")) {
        setError(QStringLiteral("Не найден tools/farm.py в %1").arg(shortenPath(m_farmerDir)));
        return false;
    }

    m_noticeDismissed = false;
    setError(QString());
    setNotice(QString());
    m_runnerLog.clear();
    m_logText.clear();
    emit runnerLogChanged();
    emit logTextChanged();
    setStopping(false);
    setStarting(true);

    m_process->setWorkingDirectory(m_farmerDir);
    m_process->setProgram(QStringLiteral("python3"));
    m_process->setArguments(QStringList{m_farmerDir + "/tools/farm.py"}
                            + farmArguments(character, stage, danger));
    m_process->setProcessChannelMode(QProcess::MergedChannels);
    m_process->start();
    return true;
}

void Backend::stopRun()
{
    if (!m_busy || m_stopping)
        return;
    setStopping(true);
    // run.sh removes a stale stop file at launch; writing after the launch
    // lets it survive the boot and be seen by the farmer.
    QTimer::singleShot(1200, this, [this] {
        if (m_stopping)
            writeStopFile();
    });
    QTimer::singleShot(30000, this, [this] {
        if (m_stopping) {
            if (m_running)
                setError(QStringLiteral("Фермер не остановился за 30 секунд — смотрите лог."));
            setStopping(false);
        }
    });
}

void Backend::writeStopFile()
{
    QDir().mkpath(m_dataDir);
    QFile file(stopPath());
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        setError(QStringLiteral("Не удалось записать farmer_stop в %1").arg(shortenPath(m_dataDir)));
        return;
    }
    file.write("stop\n");
}

void Backend::refresh()
{
    refreshStatus();
    refreshLog();
    refreshRunning();
}

bool Backend::saveFarmerDir(const QString &path)
{
    QString clean = path.trimmed();
    if (clean.startsWith(QLatin1Char('~')))
        clean = QDir::homePath() + clean.mid(1);
    clean = QDir(clean).absolutePath();
    if (!hasUsableFile(clean, "tools/farm.py") || !hasUsableFile(clean, "targets.json")) {
        setError(QStringLiteral("Это не каталог farmer: нужны tools/farm.py и targets.json"));
        return false;
    }

    QSettings().setValue(QStringLiteral("farmerDir"), clean);
    if (clean != m_farmerDir) {
        m_farmerDir = clean;
        emit farmerDirChanged();
    }
    loadTargets();
    refreshStatus();
    refreshLog();
    return true;
}

QString Backend::shortenPath(const QString &path) const
{
    const QString home = QDir::homePath();
    return path.startsWith(home) ? QStringLiteral("~") + path.mid(home.length()) : path;
}

QString Backend::fmt(qint64 value) const
{
    const QLocale ru(QLocale::Russian, QLocale::Russia);
    return ru.toString(value);
}

QString Backend::fmt1(double value) const
{
    const QLocale ru(QLocale::Russian, QLocale::Russia);
    return ru.toString(value, 'f', 1);
}

QString Backend::fmtTime(double seconds) const
{
    const qint64 total = qMax<qint64>(0, qRound64(seconds));
    return QStringLiteral("%1:%2").arg(total / 60).arg(total % 60, 2, 10, QLatin1Char('0'));
}

QString Backend::phaseLabel() const
{
    if (m_phase == QStringLiteral("boot")) return QStringLiteral("Запуск");
    if (m_phase == QStringLiteral("run")) return QStringLiteral("Фарм");
    if (m_phase == QStringLiteral("settle")) return QStringLiteral("Подведение");
    if (m_phase == QStringLiteral("keep")) return QStringLiteral("Добыча");
    if (m_phase == QStringLiteral("maint")) return QStringLiteral("Город");
    if (m_phase == QStringLiteral("done")) return QStringLiteral("Готово");
    if (m_phase == QStringLiteral("failed")) return QStringLiteral("Ошибка");
    return QStringLiteral("Остановлен");
}

QString Backend::detectFarmerDir()
{
    const QString env = qEnvironmentVariable("MIDGARD_FARMER_DIR");
    if (!env.isEmpty() && hasUsableFile(env, "tools/farm.py"))
        return QDir(env).absolutePath();

    const QString saved = QSettings().value(QStringLiteral("farmerDir")).toString();
    if (!saved.isEmpty() && hasUsableFile(saved, "tools/farm.py"))
        return QDir(saved).absolutePath();

    const QString home = QDir::homePath();
    const QString appDir = QCoreApplication::applicationDirPath();
    const QStringList candidates{
        QDir::currentPath(),
        QDir::currentPath() + "/farmer",
        appDir + "/../../farmer",
        appDir + "/../farmer",
        home + "/orca/projects/midgard-survivor/farmer",
    };
    for (const QString &candidate : candidates) {
        const QString clean = QDir::cleanPath(candidate);
        if (hasUsableFile(clean, "tools/farm.py"))
            return clean;
    }
    return home + "/orca/projects/midgard-survivor/farmer";
}

QString Backend::detectDataDir()
{
    const QString env = qEnvironmentVariable("MIDGARD_DATA_DIR");
    if (!env.isEmpty())
        return QDir(env).absolutePath();
    return QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)
           + "/godot/app_userdata/Midgard Survivors";
}
