/* entry-link: PhotonEntry's app on an Axis network door controller (ARCHITECTURE §3.2, BUILD-GUIDE §1).
 *
 * Configuration (environment; on the controller the ACAP build reads its parameters and the D-Bus service account instead, Step 7):
 *   ENTRY_LINK_CLOUD        the link service, e.g. https://link.entry.photonind.com
 *   ENTRY_LINK_STATE_DIR    where the key, the event queue and the state live (on the controller: the app's localdata)
 *   ENTRY_LINK_VAPIX        the controller's API base (default http://127.0.0.12)
 *   ENTRY_LINK_VAPIX_USER / ENTRY_LINK_VAPIX_PASS   its login (the simulator's; on the controller, the app's service account)
 *   ENTRY_LINK_MODEL / _SERIAL / _FIRMWARE          what the controller is (reported at hello)
 *   ENTRY_LINK_EVENT_POLL_MS                        how often the controller's event log is read (default 1000)
 *
 *   entry-link --sign-vector FILE   print the signature header for contract/link/vectors.json (tests)
 */
#include <curl/curl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../vendor/cjson/cJSON.h"
#include "link.h"
#include "sign.h"
#include "util.h"

static const char *env(const char *name, const char *dflt) {
    const char *v = getenv(name);
    return v && v[0] ? v : dflt;
}

static int sign_vector(const char *path) {
    char *text = read_file(path, NULL);
    cJSON *v = text ? cJSON_Parse(text) : NULL;
    free(text);
    const cJSON *hex = cJSON_GetObjectItemCaseSensitive(v, "private_key_hex");
    if (!cJSON_IsString(hex) || strlen(hex->valuestring) != 64) { fprintf(stderr, "bad vector file\n"); return 2; }
    unsigned char seed[32];
    for (int i = 0; i < 32; i++) sscanf(hex->valuestring + 2 * i, "%2hhx", &seed[i]);
    EVP_PKEY *key = key_from_seed(seed);
    const char *body = cJSON_GetObjectItemCaseSensitive(v, "body")->valuestring;
    char header[300], pub[64], kid[17];
    if (sign_request(key, (long)cJSON_GetObjectItemCaseSensitive(v, "t")->valuedouble, cJSON_GetObjectItemCaseSensitive(v, "nonce")->valuestring,
                     cJSON_GetObjectItemCaseSensitive(v, "method")->valuestring, cJSON_GetObjectItemCaseSensitive(v, "path")->valuestring,
                     body, strlen(body), header, sizeof header) != 0 || key_public(key, pub, kid) != 0) return 1;
    printf("%s\n%s\n", header, pub);
    EVP_PKEY_free(key);
    cJSON_Delete(v);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1], "--sign-vector") == 0) return sign_vector(argv[2]);
    curl_global_init(CURL_GLOBAL_DEFAULT);
    link_config cfg = {
        .cloud = env("ENTRY_LINK_CLOUD", "https://link.entry.photonind.com"),
        .state_dir = env("ENTRY_LINK_STATE_DIR", "./entry-link-state"),
        .vapix_base = env("ENTRY_LINK_VAPIX", "http://127.0.0.12"),
        .vapix_user = env("ENTRY_LINK_VAPIX_USER", NULL),
        .vapix_pass = env("ENTRY_LINK_VAPIX_PASS", NULL),
        .model = env("ENTRY_LINK_MODEL", "unknown"),
        .serial = env("ENTRY_LINK_SERIAL", "unknown"),
        .firmware = env("ENTRY_LINK_FIRMWARE", "unknown"),
        .event_poll_ms = atoi(env("ENTRY_LINK_EVENT_POLL_MS", "1000")),
    };
    if (cfg.event_poll_ms < 50) cfg.event_poll_ms = 50;
    if (!cfg.vapix_user) LOG_WARN("no controller login configured (ENTRY_LINK_VAPIX_USER): requests will be refused");
    int rc = link_run(&cfg);
    curl_global_cleanup();
    return rc;
}
