/* Small helpers shared by entry-link: logging, files, time, hashing, base64url. */
#ifndef ENTRY_LINK_UTIL_H
#define ENTRY_LINK_UTIL_H

#include <stddef.h>
#include <stdint.h>
#include <time.h>

void el_log(const char *level, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
#define LOG_INFO(...) el_log("info", __VA_ARGS__)
#define LOG_WARN(...) el_log("warn", __VA_ARGS__)
#define LOG_ERR(...) el_log("error", __VA_ARGS__)

/* Whole file into a NUL-terminated buffer (caller frees), or NULL. */
char *read_file(const char *path, size_t *len);
/* Write through a temporary file, fsync, rename: a crash leaves the old file or the new one, never half of one. 0 on success. */
int write_file_atomic(const char *path, const char *data, size_t len, int mode);
/* dir + "/" + name into buf. */
void path_join(char *buf, size_t size, const char *dir, const char *name);

/* Seconds since the epoch, UTC, of an ISO 8601 time with Z or +00:00 (fractions ignored); -1 if it cannot be read. */
time_t parse_iso_utc(const char *s);
/* Now as ISO 8601 UTC with Z. */
void now_iso(char *buf, size_t size);

void sha256_hex(const unsigned char *data, size_t len, char out[65]);
/* base64url without padding; returns the length written (out needs 4/3 len + 4). */
size_t b64url_encode(const unsigned char *in, size_t len, char *out);

#endif
