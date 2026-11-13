/* Applying compiled settings (contract/settings/axis-settings.schema.json) to the controller by difference. */
#ifndef ENTRY_LINK_APPLY_H
#define ENTRY_LINK_APPLY_H

#include "../../vendor/cjson/cJSON.h"
#include "vapix.h"

typedef struct {
    int set;       /* objects created or replaced */
    int removed;   /* stale pe- objects removed */
    int doors;     /* doors whose timings or schedule link changed */
} apply_stats;

/* 0 on success. On failure `v->fault` says why; whatever was applied before the failure stays (each step is valid on its own, and the next
 * attempt continues from the controller's real state, because every run starts by reading it). */
int apply_settings(vapix *v, const cJSON *settings, apply_stats *stats);

/* The controller's doors and the access points that open each: {"doors": [{"token", "name", "access_points": [...]}]}. NULL on failure. */
cJSON *read_inventory(vapix *v);

#endif
