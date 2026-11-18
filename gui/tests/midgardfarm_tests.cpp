#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QTemporaryDir>
#include <QtTest>

#include "backend.h"
#include "theme.h"

class MidgardFarmTests : public QObject {
    Q_OBJECT

private slots:
    void catalogLoadsPreferredOrder()
    {
        QTemporaryDir dir;
        const QString farmer = dir.path() + "/farmer";
        QVERIFY(QDir().mkpath(farmer));

        const QByteArray targets = R"({
            "characters": {
                "bard":   {"class": "archer", "job_path": 1, "label": "Bard"},
                "sniper": {"class": "archer", "job_path": 0, "label": "Sniper"},
                "sinx":   {"class": "thief",  "job_path": 0, "label": "SinX"}
            },
            "stages": {
                "payon":    "Payon Forest",
                "prontera": "Prontera Field"
            }
        })";
        const bool wrote = write(farmer + "/targets.json", targets);
        QVERIFY(wrote);

        Backend backend(farmer, dir.path() + "/data");
        QCOMPARE(backend.characters().size(), 3);
        QCOMPARE(backend.characters().first().toMap().value("id").toString(), QString("sinx"));
        QCOMPARE(backend.stages().first().toMap().value("id").toString(), QString("prontera"));

        const QStringList expected{"--char", "sniper", "--stage", "payon", "--danger", "25"};
        QCOMPARE(backend.farmArguments("sniper", "payon", 25), expected);
    }

    void statusAndLogAreRead()
    {
        QTemporaryDir dir;
        const QString farmer = dir.path() + "/farmer";
        const QString data = dir.path() + "/data";
        QVERIFY(QDir().mkpath(farmer));
        QVERIFY(QDir().mkpath(data));

        const QByteArray targets =
            R"({"characters": {"sinx": {"class": "thief", "job_path": 0, "label": "SinX"}}, "stages": {"prontera": "Prontera"}})";
        QVERIFY(write(farmer + "/targets.json", targets));

        const qint64 now = QDateTime::currentSecsSinceEpoch();
        const QString status = QString(R"({
            "phase": "run",
            "heartbeat": %1,
            "totals": {"zeny": 1234, "kills": 56, "runs": 2, "wins": 1, "losses": 1},
            "last": {"kills": 10, "zeny_gain": 100, "game_s": 60},
            "game": {"level": 7, "time": 120, "hp": 50, "max_hp": 100, "fps": 60}
        })").arg(now);
        QVERIFY(write(data + "/farmer_status.json", status.toUtf8()));
        QVERIFY(write(data + "/farmer.log", "FARMER BOOT\nCLASS_LOCKED archer\n"));

        Backend backend(farmer, data);
        backend.refresh();
        QCOMPARE(backend.phase(), QString("run"));
        QVERIFY(backend.running());
        QCOMPARE(backend.status().value("totals").toMap().value("zeny").toInt(), 1234);
        QVERIFY(backend.logText().contains("CLASS_LOCKED"));
        QVERIFY(!backend.notice().isEmpty());
    }


    void startRunSpawnsAndStops()
    {
        QTemporaryDir dir;
        const QString farmer = dir.path() + "/farmer";
        const QString data = dir.path() + "/data";
        QVERIFY(QDir().mkpath(farmer + "/tools"));
        QVERIFY(QDir().mkpath(data));
        QVERIFY(write(farmer + "/targets.json",
                      R"({"characters": {"sinx": {"class": "thief", "job_path": 0, "label": "SinX"}}, "stages": {"prontera": "Prontera"}})"));
        const QByteArray fake =
            "import json, os, pathlib, sys, time\n"
            "data = pathlib.Path(os.environ['MIDGARD_TEST_DATA'])\n"
            "stop = data / 'farmer_stop'\n"
            "status = data / 'farmer_status.json'\n"
            "status.write_text(json.dumps({'phase': 'run', 'heartbeat': int(time.time())}))\n"
            "print('fake farmer start', flush=True)\n"
            "for _ in range(60):\n"
            "    if stop.exists(): break\n"
            "    time.sleep(0.1)\n"
            "status.write_text(json.dumps({'phase': 'done', 'heartbeat': int(time.time())}))\n"
            "print('fake farmer stop', flush=True)\n";
        QVERIFY(write(farmer + "/tools/farm.py", fake));
        qputenv("MIDGARD_TEST_DATA", data.toLocal8Bit());

        Backend backend(farmer, data);
        QVERIFY(backend.startRun("sinx", "prontera", 25));
        QTRY_VERIFY_WITH_TIMEOUT(backend.running(), 3000);
        backend.stopRun();
        QTRY_VERIFY_WITH_TIMEOUT(!backend.busy(), 5000);
        QVERIFY(backend.runnerLog().contains("fake farmer stop"));
        qunsetenv("MIDGARD_TEST_DATA");
    }

    void themeFallsBack()
    {
        QTemporaryDir dir;
        Theme theme(dir.path());
        QCOMPARE(theme.accent(), QString("#FFD60A"));
        QCOMPARE(theme.background(), QString("#0e0e10"));
        QCOMPARE(theme.accentForeground(), QString("black"));
    }

    void themeReadsColours()
    {
        QTemporaryDir dir;
        QVERIFY(QDir(dir.path()).mkpath("theme"));
        const QByteArray colors =
            "accent = \"#112233\"\n"
            "background = \"#010203\"\n"
            "foreground = \"#f0f0f0\"\n"
            "selection = \"#223344\"\n";
        QVERIFY(write(dir.path() + "/theme/colors.toml", colors));

        Theme theme(dir.path());
        QCOMPARE(theme.accent(), QString("#112233"));
        QCOMPARE(theme.background(), QString("#010203"));
        QCOMPARE(theme.foreground(), QString("#f0f0f0"));
        QCOMPARE(theme.border(), QString("#223344"));
        QCOMPARE(theme.accentForeground(), QString("white"));
    }

    void themeFollowsHyprlandRounding()
    {
        QTemporaryDir dir;
        const QString response = dir.filePath("response.json");
        const QString command = dir.filePath("hyprctl");
        QVERIFY(write(command, "#!/bin/sh\ncat '" + response.toUtf8() + "'\n"));
        QVERIFY(QFile::setPermissions(command, QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner));
        QVERIFY(write(response, "{\"int\":0}"));

        Theme theme(dir.path(), nullptr, command);
        QCOMPARE(theme.radius(), 0);
        QVERIFY(write(response, "{\"int\":6}"));
        QTRY_COMPARE(theme.radius(), 6);
    }

private:
    static bool write(const QString &path, const QByteArray &contents)
    {
        QFile file(path);
        if (!file.open(QIODevice::WriteOnly))
            return false;
        const qint64 written = file.write(contents);
        file.flush();
        file.close();
        return written == contents.size();
    }
};

QTEST_MAIN(MidgardFarmTests)
#include "midgardfarm_tests.moc"
