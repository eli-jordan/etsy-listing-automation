# shellcheck shell=bash
# Gate in front of the agent lint hook for Claude Code and Grok (spec S06).
#
# The hook command sources this file (`. scripts/agent_lint_gate.sh MODE`)
# rather than running it, so it costs no second bash. After a shell command
# it decides with builtins alone, starting no process, whether the command
# could have written a file: a command that only reads ends the hook in about
# the time bash takes to start. Edits, session events and commands that may
# have written anything go on to scripts/agent_lint.py with the payload.
#
# Codex uses scripts/agent_lint_gate.py instead; both read their rules from
# scripts/agent_lint_rules.txt. Set AGENT_LINT_GATE_DECIDE=1 to print `skip`
# or `lint` instead of acting (the tests use it).

_agent_lint_root=${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}
_agent_lint_root=${_agent_lint_root//\\//}

_agent_lint_trim() {
	local text=$1
	text=${text#"${text%%[![:space:]]*}"}
	REPLY=${text%"${text##*[![:space:]]}"}
}

# Succeeds when every segment of the command in $1 only reads.
_agent_lint_read_only() {
	local command=$1 line kind value inner pattern segment allowed
	local -a rules=() unwraps=() strips=() denies=() allows=() segments=()
	mapfile -t rules <"$_agent_lint_root/scripts/agent_lint_rules.txt" || return 1
	for line in "${rules[@]}"; do
		line=${line%$'\r'}
		kind=${line%% *}
		value=${line#* }
		case $kind in
		unwrap) unwraps+=("$value") ;;
		strip) strips+=("$value") ;;
		deny) denies+=("$value") ;;
		allow) allows+=("$value") ;;
		esac
	done
	_agent_lint_trim "$command"
	command=$REPLY
	for pattern in "${unwraps[@]}"; do
		if [[ $command =~ $pattern ]]; then
			inner=${BASH_REMATCH[${#BASH_REMATCH[@]} - 1]}
			[[ ${inner: -1} == [\'\"] ]] && inner=${inner%?}
			command=$inner
			break
		fi
	done
	for value in "${strips[@]}"; do
		command=${command//"$value"/}
	done
	for pattern in "${denies[@]}"; do
		[[ $command =~ $pattern ]] && return 1
	done
	command=${command//&&/$'\n'}
	command=${command//||/$'\n'}
	command=${command//;/$'\n'}
	command=${command//|/$'\n'}
	local IFS=$'\n'
	set -f
	segments=($command)
	set +f
	for segment in "${segments[@]}"; do
		_agent_lint_trim "$segment"
		segment=$REPLY
		[[ -z $segment ]] && continue
		allowed=1
		for pattern in "${allows[@]}"; do
			[[ $segment =~ $pattern ]] && allowed=0 && break
		done
		((allowed == 0)) || return 1
	done
	return 0
}

# Succeeds when the payload in $1 is a shell command that only reads.
_agent_lint_skip() {
	local payload=$1 command
	local tool='"tool_name"[[:space:]]*:[[:space:]]*"Bash"'
	local field='"command"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"'
	[[ $payload =~ $tool ]] || return 1
	[[ $payload =~ $field ]] || return 1
	command=${BASH_REMATCH[1]}
	# JSON escapes this does not decode (\uXXXX could spell a `>`) go to the
	# full check rather than risk a wrong skip.
	[[ $command == *'\u'* ]] && return 1
	command=${command//\\\"/\"}
	command=${command//\\n/$'\n'}
	command=${command//\\t/ }
	command=${command//\\\\/\\}
	_agent_lint_read_only "$command"
}

_agent_lint_main() {
	local mode=${1:-edit} payload="" python
	IFS= read -r -d '' payload
	if [[ $mode == edit ]] && _agent_lint_skip "$payload"; then
		[[ -n ${AGENT_LINT_GATE_DECIDE:-} ]] && echo skip
		exit 0
	fi
	if [[ -n ${AGENT_LINT_GATE_DECIDE:-} ]]; then
		echo lint
		exit 0
	fi
	for python in "$_agent_lint_root/.venv/Scripts/python.exe" "$_agent_lint_root/.venv/bin/python"; do
		[[ -x $python ]] && exec "$python" -S "$_agent_lint_root/scripts/agent_lint.py" "$mode" <<<"$payload"
	done
	exec uv run --no-project python "$_agent_lint_root/scripts/agent_lint.py" "$mode" <<<"$payload"
}

_agent_lint_main "$@"
