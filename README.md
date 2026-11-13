# PhotonEntry

Cloud access control with video intercom for integrators, in the Photon suite (working folder name `photonaccess`). Autonomous Axis door
controllers take their access settings from the cloud through `entry-link`, an app on the controller, and send their events back.

- Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Build brief: [docs/BUILD-GUIDE.md](docs/BUILD-GUIDE.md). Working on it: [docs/DEV.md](docs/DEV.md).
- The suite: `~/projects/photon-suite/ARCHITECTURE.md`.
- Tests: `scripts/test-all.sh` (no hardware needed: `sim/` simulates the Axis controller).
