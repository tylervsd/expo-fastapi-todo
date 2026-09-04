#!/bin/sh

check_docker_cli() {
  if ! command -v docker >/dev/null 2>&1; then
    doctor_missing 'Docker is missing; install Docker Desktop; see troubleshooting#docker-cli.'
    return
  fi

  docker_output=$(docker --version 2>/dev/null) || {
    doctor_fail 'Docker version could not be detected; see troubleshooting#docker-cli.'
    return
  }
  docker_first_line=$(printf '%s\n' "$docker_output" | sed -n '1p')
  doctor_pass "$docker_first_line"
}

check_docker_daemon() {
  if ! command -v docker >/dev/null 2>&1; then
    doctor_missing 'Docker is missing; install Docker Desktop; see troubleshooting#docker-daemon.'
    return
  fi

  if docker info >/dev/null 2>&1; then
    doctor_pass 'Docker daemon is reachable'
  else
    doctor_fail 'Docker is installed but the daemon is not reachable; see troubleshooting#docker-daemon.'
  fi
}

check_docker_compose() {
  if ! command -v docker >/dev/null 2>&1; then
    doctor_missing 'Docker is missing; install Docker Desktop; see troubleshooting#docker-compose.'
    return
  fi

  compose_output=$(docker compose version 2>/dev/null) || {
    doctor_fail 'Docker Compose is unavailable; see troubleshooting#docker-compose.'
    return
  }
  compose_first_line=$(printf '%s\n' "$compose_output" | sed -n '1p')
  doctor_pass "$compose_first_line"
}

doctor_register docker.cli required check_docker_cli
doctor_register docker.daemon required check_docker_daemon
doctor_register docker.compose required check_docker_compose
