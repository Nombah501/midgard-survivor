#pragma once

#include <QFileSystemWatcher>
#include <QObject>
#include <QProcess>
#include <QTimer>

// Omarchy theme bridge: accent, backgrounds, text colours and Hyprland's
// effective window rounding. The theme files are replaced on a theme switch,
// so the watcher is re-armed after every change.
class Theme : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString accent READ accent NOTIFY changed)
    Q_PROPERTY(QString accentForeground READ accentForeground NOTIFY changed)
    Q_PROPERTY(QString background READ background NOTIFY changed)
    Q_PROPERTY(QString surface READ surface NOTIFY changed)
    Q_PROPERTY(QString border READ border NOTIFY changed)
    Q_PROPERTY(QString foreground READ foreground NOTIFY changed)
    Q_PROPERTY(QString muted READ muted NOTIFY changed)
    Q_PROPERTY(QString red READ red NOTIFY changed)
    Q_PROPERTY(QString warning READ warning NOTIFY changed)
    Q_PROPERTY(int radius READ radius NOTIFY changed)

public:
    explicit Theme(const QString &currentDirectory = {}, QObject *parent = nullptr,
                   const QString &hyprctl = {});
    ~Theme() override;

    QString accent() const { return m_accent; }
    QString accentForeground() const;
    QString background() const { return m_background; }
    QString surface() const { return m_surface; }
    QString border() const { return m_border; }
    QString foreground() const { return m_foreground; }
    QString muted() const { return m_muted; }
    QString red() const { return m_red; }
    QString warning() const { return m_warning; }
    int radius() const { return m_radius; }

    static QString readColor(const QString &path, const QString &key, const QString &fallback);
    static QString readAccent(const QString &path);

signals:
    void changed();

private:
    void reload();
    void refreshRounding();

    QString m_directory;
    QString m_accent = "#FFD60A";
    QString m_background = "#0e0e10";
    QString m_surface = "#1a1a1e";
    QString m_border = "#2b302b";
    QString m_foreground = "#dfede5";
    QString m_muted = "#91ad9f";
    QString m_red = "#d88d91";
    QString m_warning = "#c5cc91";
    QFileSystemWatcher m_watcher;
    QTimer m_debounce;
    QString m_hyprctl;
    int m_radius = 0;
    QProcess m_roundingProcess;
    QTimer m_roundingPoll, m_roundingTimeout;
};
