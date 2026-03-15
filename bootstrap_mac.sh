#!/bin/bash

# Mac-compatible version of bootstrap.sh
#
# Differences from the Linux version:
#   - Uses Homebrew instead of apt-get for system packages
#   - Downloads the macOS Elm binary instead of the Linux one
#   - Uses environment_mac.yaml (strips Linux-only conda packages)
#   - Does not use sudo (Homebrew does not require it)
#
# Notes:
#   - Real-time process priorities (run_priority in graph YAMLs) are not
#     supported on macOS. The supervisor will skip priority-setting on Mac.
#   - Tested on macOS with Apple Silicon and Intel. Some pip packages with
#     pinned old versions may need relaxing if they have no macOS wheels.

RED="\e[31m"
GREEN="\e[32m"
DEFAULT="\e[39m"

error () {
    echo -e "${RED}Error: ${DEFAULT}$1"
    exit 1
}

info () {
    echo -e "${GREEN}$1${DEFAULT}"
}

checkStatus () {
    [ "$1" == "0" ] || error "$2"
}

# Check that Homebrew is installed
[ "`which brew`" ] || error "Homebrew is not installed. Install it from https://brew.sh and rerun this script."

# List of Homebrew packages to install as dependencies.
# On Mac, SDL2 dev headers are bundled with the library formula (no separate -dev packages).
dependencies=(
automake
libtool
curl
pkg-config
sdl2
sdl2_image
sdl2_gfx
sdl2_ttf
node
)

# Install packages
for dep in ${dependencies[@]}; do
    info "Installing ${dep}"
    brew install ${dep}
    checkStatus $? "failed to install ${dep}"
    info "Successfully installed ${dep}"
done

# Install Elm compiler (macOS binary)
install_elm=false
ROOT=`dirname "$0"`
elmPath=${ROOT}/bin
[ -d "${elmPath}" ] || mkdir -p "${elmPath}"
[ -x "${elmPath}/elm" ] || install_elm=true

if ${install_elm}; then
    info "Installing elm to ${elmPath}"
    pushd ${elmPath}

    # Detect Apple Silicon vs Intel and download the appropriate binary
    ARCH=$(uname -m)
    if [ "${ARCH}" == "arm64" ]; then
        # Apple Silicon: use Rosetta-compatible x86_64 binary (no native ARM build for 0.19.1)
        info "Detected Apple Silicon (arm64) - downloading x86_64 Elm binary (runs via Rosetta 2)"
    else
        info "Detected Intel (x86_64)"
    fi

    curl -L -o elm.gz https://github.com/elm/compiler/releases/download/0.19.1/binary-for-mac-64-bit.gz
    checkStatus $? "failed to download Elm binary"
    gunzip elm.gz
    chmod +x elm
    popd
fi

# Check conda is installed
[ "`which conda`" ] || error "conda is not installed. Please install miniconda or anaconda and rerun this script."

# Create or update the rt conda environment using the Mac-specific environment file
info "Updating real-time conda env (using environment_mac.yaml)"
conda env update --file ${ROOT}/environment_mac.yaml --prune
checkStatus $? "conda update failed"
info "conda env successfully updated"

info "Updating git submodules"
git submodule update --init --recursive
checkStatus $? "failed to update git submodules"

info "Your environment is ready!"
info "Run \`conda activate rt\` before running make"
