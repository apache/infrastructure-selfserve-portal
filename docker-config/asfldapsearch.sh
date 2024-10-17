#!/usr/bin/env bash

case "$@" in
    *ou=project,ou=groups,dc=apache,dc=org*)
    # Need at least 100 entries
    for i in aa bb cc dd ee ff gg hh ii jj kk
    do
        for j in ll mm nn oo pp qq rr ss tt uu vv
        do
            prj=$i$j
            echo dn: cn=$prj,ou=project,ou=groups,dc=apache,dc=org
            echo cn: $prj
            echo ''
        done
    done
    ;;
    *)
        echo "Invalid request" >&1
        exit 1
    ;;
esac
