#!/usr/bin/env bash
# Creates the GPG key that signs the repository, in a throwaway keyring, and writes the
# armored private key to ./flatpak-repo-signing.key (mode 600). Store it as the
# GPG_PRIVATE_KEY secret, then delete the file:
#
#   gh secret set GPG_PRIVATE_KEY < flatpak-repo-signing.key
#   shred -u flatpak-repo-signing.key
#
# The key has no passphrase because CI has to use it unattended; the secret is the
# protection. The public key is derived from it at publish time and needs no storage.
set -euo pipefail

name=${1:-"Flatpak repository signing key"}
home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT
chmod 700 "$home"

gpg --homedir "$home" --batch --quiet --pinentry-mode loopback --passphrase '' \
  --quick-generate-key "$name" ed25519 sign never

umask 077
gpg --homedir "$home" --batch --armor --export-secret-keys > flatpak-repo-signing.key
echo "Wrote flatpak-repo-signing.key"
gpg --homedir "$home" --list-keys --with-colons | awk -F: '/^fpr:/ {print "Fingerprint: " $10; exit}'
