#!/bin/sh
while [ "$#" -ge 2 ] && [ "$1" = "-c" ]; do
    shift 2
done
case "$1" in
    --version)
        printf 'git version modelrig-rsi-test-1\n'
        ;;
    rev-parse)
        if [ "$2" = "--verify" ]; then
            IFS= read -r main_sha < .modelrig-main-sha || exit 7
            printf '%s\n' "$main_sha"
        else
            exit 8
        fi
        ;;
    *)
        exit 9
        ;;
esac
