#!/bin/sh

check_repository_files() {
  missing=''
  for required_path in \
    Brewfile \
    LICENSE \
    README.md \
    package.json \
    pnpm-lock.yaml \
    pnpm-workspace.yaml \
    .python-version \
    docs/curriculum-roadmap.md \
    docs/setup/macos.md \
    docs/setup/troubleshooting.md; do
    if [ ! -e "$PROJECT_ROOT/$required_path" ]; then
      if [ -n "$missing" ]; then
        missing="$missing $required_path"
      else
        missing=$required_path
      fi
    fi
  done

  if [ -n "$missing" ]; then
    doctor_fail "missing required repository files: $missing; see troubleshooting#repository-files."
  else
    doctor_pass 'required repository files are present'
  fi
}

doctor_register repository.files required check_repository_files
