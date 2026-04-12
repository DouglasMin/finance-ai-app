#!/bin/bash
# agentcore dev wrapper — exports env vars into the parent shell so
# the CLI forwards them into the container. Mirrors the imageeditoragent pattern.

set -a
source ./agentcore/.env.local
set +a

export AWS_PROFILE="${AWS_PROFILE:-developer-dongik}"

agentcore dev "$@"
