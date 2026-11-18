// Midgard Farm — choose a character and a location, then run the farmer.

#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QGuiApplication>
#include <QIcon>
#include <QImage>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QTimer>
#include <QUrl>
#include <cstdlib>

#include "backend.h"
#include "theme.h"

int main(int argc, char *argv[])
{
    for (int i = 1; i < argc; ++i) {
        if (QString::fromLocal8Bit(argv[i]) == QLatin1String("--screenshot")) {
            qputenv("QT_QPA_PLATFORM", "offscreen");
            qputenv("QSG_RHI_BACKEND", "software");
            break;
        }
    }

    QGuiApplication app(argc, argv);
    app.setOrganizationName(QStringLiteral("Midgard"));
    app.setApplicationName(QStringLiteral("midgardfarm"));
    app.setApplicationDisplayName(QStringLiteral("Midgard Farm"));
    app.setApplicationVersion(QStringLiteral("0.1.0"));
    app.setDesktopFileName(QStringLiteral("midgardfarm"));
    app.setWindowIcon(QIcon::fromTheme(QStringLiteral("midgardfarm")));

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("Choose a character and a location for the Midgard Survivors farmer."));
    parser.addHelpOption();
    parser.addVersionOption();
    const QCommandLineOption farmerOption(
        QStringLiteral("farmer-dir"), QStringLiteral("Path to the farmer directory."), QStringLiteral("path"));
    const QCommandLineOption dataOption(
        QStringLiteral("data-dir"), QStringLiteral("Override the game's user:// directory (for tests)."),
        QStringLiteral("path"));
    const QCommandLineOption screenshotOption(
        QStringLiteral("screenshot"), QStringLiteral("Save a window screenshot and exit."), QStringLiteral("path"));
    parser.addOption(farmerOption);
    parser.addOption(dataOption);
    parser.addOption(screenshotOption);
    parser.process(app);

    if (parser.isSet(farmerOption))
        qputenv("MIDGARD_FARMER_DIR", parser.value(farmerOption).toLocal8Bit());
    if (parser.isSet(dataOption))
        qputenv("MIDGARD_DATA_DIR", parser.value(dataOption).toLocal8Bit());

    QQuickStyle::setStyle(QStringLiteral("Material"));

    Theme theme;
    Backend backend;

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("theme"), &theme);
    engine.rootContext()->setContextProperty(QStringLiteral("backend"), &backend);
    engine.load(QUrl(QStringLiteral("qrc:/Main.qml")));
    if (engine.rootObjects().isEmpty())
        return 1;

    if (parser.isSet(screenshotOption)) {
        const QString path = parser.value(screenshotOption);
        QTimer::singleShot(1200, &app, [&engine, path] {
            QQuickWindow *window = qobject_cast<QQuickWindow *>(engine.rootObjects().constFirst());
            if (window != nullptr) {
                const QImage image = window->grabWindow();
                if (!image.isNull())
                    image.save(path);
            }
            // The screenshot window may be guarded by the "farm is running"
            // close dialog; bypass the normal close path for this test mode.
            std::_Exit(0);
        });
    }

    return app.exec();
}
