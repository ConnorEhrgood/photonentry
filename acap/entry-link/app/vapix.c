#include "vapix.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

cJSON *vapix_call(vapix *v, const char *endpoint, const char *method, cJSON *msg) {
    cJSON *req = cJSON_CreateObject();
    cJSON_AddItemToObject(req, method, msg ? msg : cJSON_CreateObject());
    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    char url[512];
    snprintf(url, sizeof url, "%s/vapix/%s", v->base, endpoint);
    http_result r = http_post_json(v->http, url, body, strlen(body), v->user, v->pass, NULL, 30);
    free(body);
    cJSON *out = NULL;
    if (r.status == 0) {
        snprintf(v->fault, sizeof v->fault, "%s: %s", method, r.error);
    } else {
        out = cJSON_Parse(r.body);
        if (r.status != 200 || !cJSON_IsObject(out)) {
            const cJSON *sub = cJSON_GetObjectItemCaseSensitive(out, "FaultSubCode");
            const cJSON *code = cJSON_GetObjectItemCaseSensitive(out, "FaultCode");
            const cJSON *msgf = cJSON_GetObjectItemCaseSensitive(out, "FaultMsg");
            snprintf(v->fault, sizeof v->fault, "%s: HTTP %ld %s %s %s", method, r.status,
                     cJSON_IsString(code) ? code->valuestring : "", cJSON_IsString(sub) ? sub->valuestring : "",
                     cJSON_IsString(msgf) ? msgf->valuestring : "");
            cJSON_Delete(out);
            out = NULL;
        }
    }
    http_result_free(&r);
    return out;
}

cJSON *vapix_list(vapix *v, const char *endpoint, const char *method, const char *key) {
    cJSON *all = cJSON_CreateArray();
    char *start = NULL;
    for (int page = 0; page < 100000; page++) {
        cJSON *msg = cJSON_CreateObject();
        if (start) cJSON_AddStringToObject(msg, "StartReference", start);
        free(start);
        start = NULL;
        cJSON *out = vapix_call(v, endpoint, method, msg);
        if (!out) { cJSON_Delete(all); return NULL; }
        cJSON *items = cJSON_DetachItemFromObjectCaseSensitive(out, key);
        cJSON *item;
        while (items && (item = cJSON_DetachItemFromArray(items, 0)) != NULL) cJSON_AddItemToArray(all, item);
        cJSON_Delete(items);
        const cJSON *next = cJSON_GetObjectItemCaseSensitive(out, "NextStartReference");
        if (cJSON_IsString(next) && next->valuestring[0]) start = strdup(next->valuestring);
        cJSON_Delete(out);
        if (!start) return all;
    }
    free(start);
    cJSON_Delete(all);
    snprintf(v->fault, sizeof v->fault, "%s: too many pages", method);
    return NULL;
}
