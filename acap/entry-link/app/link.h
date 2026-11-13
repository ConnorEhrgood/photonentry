/* The link to the PhotonEntry cloud (contract/link/): hello and claim, then two threads.
 *
 *   control thread  holds a long-polled sync open (wait=true): new settings and commands arrive within about a second;
 *                   re-applies the settings it holds every hour (drift) and retries a failed version every minute;
 *                   reads the controller's inventory at start and every ten minutes.
 *   events thread   every second reads new events from the controller's log into the queue and, when there is anything queued or any
 *                   command result to report, sends it (wait=false).
 *
 * Either thread may receive settings or commands in its reply (the cloud answers every sync), so both handle replies the same way, under one
 * lock. Nothing here takes part in an access decision: if this program stops, the controller goes on deciding alone. */
#ifndef ENTRY_LINK_LINK_H
#define ENTRY_LINK_LINK_H

typedef struct {
    const char *cloud;          /* https://link.entry.photonind.com */
    const char *state_dir;
    const char *vapix_base;     /* http://127.0.0.12 */
    const char *vapix_user;
    const char *vapix_pass;
    const char *model, *serial, *firmware;
    int event_poll_ms;
} link_config;

/* Runs until a SIGTERM or SIGINT; returns the process exit status. */
int link_run(const link_config *cfg);

#endif
