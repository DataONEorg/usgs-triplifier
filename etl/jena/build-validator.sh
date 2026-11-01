#!/bin/sh
# Compiles ValidateRelease.java against a Jena distribution and writes
# validate-release.jar into that distribution's directory.
# Usage: build-validator.sh <Jena directory>
set -eu

JENA_HOME="$1"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
CLASSES="$(mktemp -d)"
trap 'rm -rf "$CLASSES"' EXIT

javac -proc:none -cp "$JENA_HOME/lib/*" -d "$CLASSES" "$SOURCE_DIR/ValidateRelease.java"
jar cf "$JENA_HOME/validate-release.jar" -C "$CLASSES" .
