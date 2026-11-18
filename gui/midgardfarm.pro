QT += core gui qml quick quickcontrols2

CONFIG += c++17 release
TARGET = midgardfarm
TEMPLATE = app

INCLUDEPATH += src

HEADERS += \
    src/backend.h \
    src/theme.h

SOURCES += \
    src/main.cpp \
    src/backend.cpp \
    src/theme.cpp

RESOURCES += src/resources.qrc
