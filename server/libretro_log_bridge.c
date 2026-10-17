/*
 * Libretro log callback with the required variadic C ABI.
 *
 * Python ctypes cannot safely provide a variadic log callback. Some builds
 * of the VICE Libretro fallback logger call vfprintf with a NULL FILE* and
 * crash in retro_init. Use this callback with GET_LOG_INTERFACE instead.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include <stdarg.h>
#include <stdio.h>
#include <unistd.h>

__attribute__((visibility("default")))
void retro_log_bridge(int level, const char *format, ...)
{
    (void)level;
    if (format == NULL)
        return;
    char buf[2048];
    va_list ap;
    va_start(ap, format);
    int n = vsnprintf(buf, sizeof(buf), format, ap);
    va_end(ap);
    if (n > 0) {
        size_t len = (size_t)n < sizeof(buf) ? (size_t)n : sizeof(buf) - 1;
        (void)write(STDERR_FILENO, buf, len);
    }
}
