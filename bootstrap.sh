#!/bin/bash

# This script will install debian pkg dependencies and activate
# the reat-time conda environment (rt) defined by environment.yaml

# Notes
#   - this has only been tested on Ubuntu 18.04
#   - libevent-2.1-6 was already installed on my machine,
#     so assuming it comes default with Ubuntu 18.04

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

# List of apt packages to install as dependencies.
# All of these should be found in Ubuntu 18.04 default repos.
# To add a dependency, just add the pkg name to the list.
dependencies=(
libsqlite3-dev
automake
libtool
curl
libsdl2-2.0-0
libsdl2-dev
libsdl2-image-2.0-0
libsdl2-image-dev
libsdl2-gfx-1.0-0
libsdl2-gfx-dev
libsdl2-ttf-dev
)

sudo apt-get update

# install pkgs in $dependencies
for dep in ${dependencies[@]}; do
    info "Installing ${dep}"
    sudo apt-get -y install ${dep}
    checkStatus $? "failed to install ${dep}"
    info "Successfully installed ${dep}"
done

sudo snap install yq

# check if elm command is available. If not prompt user for installation.
install_elm=false
ROOT=`dirname "$0"`
elmPath=${ROOT}/bin
[ -d "${elmPath}" ] || mkdir -p "${elmPath}" # make bin/ sense it will be used by make anyway
[ -x "${elmPath}/elm" ] || install_elm=true

# install elm to the project bin path
if ${install_elm}; then
    info "Installing elm to ${elmPath}"
    pushd ${elmPath}
    curl -L -o elm.gz https://github.com/elm/compiler/releases/download/0.19.1/binary-for-linux-64-bit.gz
    gunzip elm.gz
    chmod +x elm
    popd
fi

# check conda is installed
# which conda should return a path of > 0 length if installed
[ "`which conda`" ] || error "conda is not installed. Please install it and rerun this script"

# create conda env from file - in case it has been created, just update it.
info "Updating real-time conda env"
conda env update --file environment.yaml --prune
checkStatus $? "conda update failed"
info "conda env succesfully updated"

info "Updating git submodules"
git submodule update --init --recursive
checkStatus $? "failed to update git submodules"
info "Your environment is ready!"
info "Run \`conda activate rt\` before running make"
