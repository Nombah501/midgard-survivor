#pragma once

#include <QObject>
#include <QProcess>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>

// The GUI's whole world: the farmer directory, the target catalogue, the
// farmer process, and the status/log files it writes.
class Backend : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString farmerDir READ farmerDir NOTIFY farmerDirChanged)
    Q_PROPERTY(QString dataDir READ dataDir CONSTANT)
    Q_PROPERTY(QVariantList characters READ characters NOTIFY targetsChanged)
    Q_PROPERTY(QVariantList stages READ stages NOTIFY targetsChanged)
    Q_PROPERTY(QVariantMap status READ status NOTIFY statusChanged)
    Q_PROPERTY(QString phase READ phase NOTIFY statusChanged)
    Q_PROPERTY(bool running READ running NOTIFY runningChanged)
    Q_PROPERTY(bool starting READ starting NOTIFY startingChanged)
    Q_PROPERTY(bool stopping READ stopping NOTIFY stoppingChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString error READ error NOTIFY errorChanged)
    Q_PROPERTY(QString notice READ notice NOTIFY noticeChanged)
    Q_PROPERTY(QString logText READ logText NOTIFY logTextChanged)
    Q_PROPERTY(QString runnerLog READ runnerLog NOTIFY runnerLogChanged)

public:
    explicit Backend(QObject *parent = nullptr);
    Backend(const QString &farmerDir, const QString &dataDir, QObject *parent = nullptr);

    QString farmerDir() const { return m_farmerDir; }
    QString dataDir() const { return m_dataDir; }
    QVariantList characters() const { return m_characters; }
    QVariantList stages() const { return m_stages; }
    QVariantMap status() const { return m_status; }
    QString phase() const { return m_phase; }
    bool running() const { return m_running; }
    bool starting() const { return m_starting; }
    bool stopping() const { return m_stopping; }
    bool busy() const { return m_busy; }
    QString error() const { return m_error; }
    QString notice() const { return m_notice; }
    QString logText() const { return m_logText; }
    QString runnerLog() const { return m_runnerLog; }

    Q_INVOKABLE bool startRun(const QString &character, const QString &stage, int danger);
    Q_INVOKABLE void stopRun();
    Q_INVOKABLE void refresh();
    Q_INVOKABLE bool saveFarmerDir(const QString &path);
    Q_INVOKABLE void clearError();
    Q_INVOKABLE void clearNotice();
    Q_INVOKABLE QString shortenPath(const QString &path) const;
    Q_INVOKABLE QString fmt(qint64 value) const;
    Q_INVOKABLE QString fmt1(double value) const;
    Q_INVOKABLE QString fmtTime(double seconds) const;
    Q_INVOKABLE QString phaseLabel() const;

    // Exposed for the backend test; startRun feeds the same list to python3.
    QStringList farmArguments(const QString &character, const QString &stage, int danger) const;

    static QString detectFarmerDir();
    static QString detectDataDir();

signals:
    void farmerDirChanged();
    void targetsChanged();
    void statusChanged();
    void runningChanged();
    void startingChanged();
    void stoppingChanged();
    void busyChanged();
    void errorChanged();
    void noticeChanged();
    void logTextChanged();
    void runnerLogChanged();

private:
    void init();
    void loadTargets();
    void refreshStatus();
    void refreshLog();
    void refreshRunning();
    void appendRunner(const QString &text);
    void setError(const QString &text);
    void setNotice(const QString &text);
    void setStarting(bool value);
    void setStopping(bool value);
    bool statusActive() const;
    void writeStopFile();
    QString statusPath() const;
    QString logPath() const;
    QString stopPath() const;
    void updateBusy();

    QString m_farmerDir;
    QString m_dataDir;
    QVariantList m_characters;
    QVariantList m_stages;
    QVariantMap m_status;
    QString m_phase;
    QString m_error;
    QString m_notice;
    QString m_logText;
    QString m_runnerLog;
    bool m_running = false;
    bool m_starting = false;
    bool m_stopping = false;
    bool m_busy = false;
    bool m_noticeDismissed = false;
    QProcess *m_process = nullptr;
    QTimer m_timer;
};
