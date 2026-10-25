# Video script: Scenario 9, Safety and Fault Recovery (about 5 minutes)

Spoken length is about 700 words at a calm 140 words per minute. Text in
**[BRACKETS]** is a screen action or a value to fill in after the run. Do not
read a number aloud until it comes from a recorded run. As of this revision,
T16–T18 are NOT RUN (see `docs/test-matrix.md`).

---

## 1. Why safety is separate (0:00–0:40)

**[Screen: architecture diagram, safety_supervisor highlighted]**

Scenario 9 is about what happens when something goes wrong. In our Smart
Mobility Hub, every bus and robot motion command passes through one
independent node, the safety supervisor. Planners and controllers can only
propose motion. They cannot drive the actuators directly.

The rule we followed is simple. Invalid or stale input is never treated as
clear. If the supervisor cannot trust an input, that input is UNKNOWN, and
unknown means stop.

---

## 2. The latched stop (0:40–1:50)

**[Screen: terminal with the safety state topic and the robot moving]**

First, the latched stop. The robot is moving. At ten seconds we assert an
emergency stop. The supervisor runs a 20 hertz safety tick. The requirement
is that the final zero command goes out within 0.2 seconds of the supervisor
receiving the fault.

**[Screen: zero command appears; show latency measurement]**

Here the zero command was sent in **[MEASURED LATENCY]** seconds. We report
the actual simulator velocity separately, because a zero command and a
stopped robot are two different measurements. The velocity reached zero after
**[MEASURED TIME]** seconds.

Now the important part. At twelve seconds, the false input goes away. The
latch stays on. A clear input does not restart anything.

**[Screen: clear service called while the hazard is still present]**

When we ask for a reset while the situation is still unsafe, the supervisor
denies it and gives the reason. Only after the hazard is truly gone does a
reset succeed. Even then, the robot does not move. Clearing a latch never
restarts a mission. The operator must send a new goal.

---

## 3. Independent watchdogs (1:50–2:50)

**[Screen: process list, then kill the controller]**

Next, the watchdogs. We deliberately kill the controller. The supervisor sees
the candidate command gap grow past 0.5 seconds and stops motion.

Then we kill the supervisor itself. This is why the actuator adapters have
their own expiry. Each adapter independently stops when its command expires
or when the supervisor goes silent. So the safety does not depend on one
process staying alive.

**[Screen: log lines with reason and latency]**

For each trial we log the reason, the zero-command latency, and the measured
velocity. We also test the robot odometry gap: if odometry is silent for more
than one second, the robot stops. Each fault runs five times, at different
phases of the mission, because a fault at pickup is not the same as a fault
while crossing.

---

## 4. Service loss and stale data (2:50–3:50)

**[Screen: planner node stopped; client log with retries]**

Now service failures. We remove the route planner, or make it reply late. The
client uses a one second timeout and at most two retries. After that it fails
with an explicit error. It never hangs, and the robot does not move.

If a reply arrives late, after the client has given up, it is discarded. We
never execute a stale path.

**[Screen: list of fault injections]**

The same idea covers the other faults in our map: camera silence or frozen
timestamps, duplicate reservations, stale parking sensing, and a crossing
owner that disappears. In each case the system reports an outcome that is
explicit: timeout, rejection, no route, or reset. Nothing is silent.

---

## 5. Results and honest limits (3:50–5:00)

**[Screen: results table from the evidence files]**

Here are the results. For the latched stop, **[N]** of five repetitions met
the 0.2 second bound, with a worst case of **[VALUE]** seconds. For the
watchdog, **[N]** of five trials stopped correctly. For service loss,
**[N]** of five ended with an explicit failure and zero motion.

**[If any trial failed, say so here and show the evidence file.]**

I want to be clear about the limits. These results come from the simulator,
not from real hardware. We use monotonic time for latency on the same
machine, and we document where simulation time and wall time differ. Our
mocks and pure Python tests do not prove the ROS integration, so we rely on
the real node runs shown here.

To summarize: motion goes through one supervisor, stale input means stop, a
latch survives false input, and recovery is always deliberate. Thank you.

---

## Before recording

- Run T16, T17 and T18 and save the evidence. Replace every **[BRACKET]** with
  a recorded value, and record the commit hash in the evidence file.
- If a test fails or was not run, say so in section 5 and keep the status
  words distinct: PASS, FAIL, BLOCKED, NOT RUN.
- Source requirement: assignment §16 p22. Total video length is 20–30 minutes
  per the instructor announcement. This segment fits the "13–21 integrated
  S1–S9 demos" block in `docs/submission.md`.
