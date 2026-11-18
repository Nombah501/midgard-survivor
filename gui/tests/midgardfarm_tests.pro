QT += core gui testlib

CONFIG += c++17 testcase
TARGET = midgardfarm_tests
TEMPLATE = app

INCLUDEPATH += ../src

HEADERS += \
    ../src/backend.h \
    ../src/theme.h

SOURCES += \
    midgardfarm_tests.cpp \
    ../src/backend.cpp \
    ../src/theme.cpp
