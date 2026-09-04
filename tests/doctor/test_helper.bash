setup_fake_path() {
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  ORIGINAL_PATH=$PATH
  export ORIGINAL_PATH
  PATH="$FAKE_BIN:$PATH"
  export PATH
}

fake_command() {
  name=$1
  body=$2
  {
    printf '%s\n' '#!/bin/sh'
    printf '%s\n' "$body"
  } >"$FAKE_BIN/$name"
  chmod +x "$FAKE_BIN/$name"
}
