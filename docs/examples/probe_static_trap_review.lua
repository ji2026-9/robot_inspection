-- REVIEW COPY ONLY. Not uploaded to, compiled on, or run by the controller.
-- DobotStudio Pro 4.6 installed help: script/Program Trap.html; Program Manage.html;
-- script/IO.html (DI returns ON/OFF); script/lua_var.html (local variables).
-- Static DI/interrupt diagnostic only. This file contains NO motion command.
-- Operator must first confirm robot stationary and no other motion program.
-- It does NOT protect official manual jogging, or prove braking/overtravel.
-- Run as a separate diagnostic project, never concatenate into a motion project.
--
-- Two phases, two operator touches:
--   phase 1 polls DI(1) in plain Lua and calls StopMove, but only proves the
--   condition and the command are usable. Waiting on a string condition would
--   need a second syntax guess, so the poll avoids that ambiguity.
--   phase 2 registers a Trap so the interrupt path that actually matters for
--   future script-driven motion is exercised on its own result line.

Print("PROBE_STATIC_START")
Print(DI(1))

local t0 = Systime()
local phase1 = false
while (Systime() - t0) < 30000 do
    if DI(1) == ON then
        phase1 = true
        break
    end
    Wait(20)
end

if phase1 then
    StopMove(0)
    Print("PHASE1_OK_DI1_ON_STOPMOVE_CALLED")
else
    Print("PHASE1_TIMEOUT")
end

probe_trap_fired = false

function ProbeTrapHandler()
    probe_trap_fired = true
    StopMove(0)
    Print("PHASE2_TRAP_FIRED")
end

Trap("probe_static_trap", "DI(1)==1", ProbeTrapHandler)
Print("PHASE2_READY_TOUCH_AGAIN")
Wait(30000)
DestroyTrap("probe_static_trap")

if probe_trap_fired then
    Print("PHASE2_TRAP_OK")
else
    Print("PHASE2_TRAP_NOT_FIRED")
end

Print("PROBE_STATIC_DONE")
