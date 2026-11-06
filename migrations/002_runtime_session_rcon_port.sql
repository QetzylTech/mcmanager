-- Migration 002: runtime_sessions.rcon_port
--
-- The RCON control/save-coordination channel needs the session's RCON port
-- after a manager restart (boot reconciliation). The port is provisioned on
-- the open session row by the lifecycle service at spawn and read by the
-- RCON save coordinator; it is neither derivable from world_instances.port
-- nor stored in launch_args_snapshot (which is the launch-argv record).
ALTER TABLE runtime_sessions ADD COLUMN rcon_port INTEGER NULL;
