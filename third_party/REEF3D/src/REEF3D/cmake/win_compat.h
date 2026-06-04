#pragma once

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef _USE_MATH_DEFINES
#define _USE_MATH_DEFINES
#endif

#include <algorithm>
#include <cmath>
#include <direct.h>

#ifdef _MSC_VER
#define mkdir(path, mode) _mkdir(path)
#endif
#endif
