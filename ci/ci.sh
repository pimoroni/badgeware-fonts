export TERM=${TERM:="xterm-256color"}

SCRIPT_PATH=${BASH_SOURCE-$0}
SCRIPT_PATH=$(dirname "$SCRIPT_PATH")
SCRIPT_PATH=$(realpath "$SCRIPT_PATH")

if [ -z ${CI_USE_ENV+x} ] || [ -z ${CI_PROJECT_ROOT+x} ] || [ -z ${CI_BUILD_ROOT+x} ]; then
    export CI_PROJECT_ROOT=$(realpath "$SCRIPT_PATH/..")
    export CI_BUILD_ROOT=$(pwd)
fi

function ci_build_all {
    for file in $CI_PROJECT_ROOT/*/; do
        if [ -f "$file/build.sh" ]; then
            cd $file
            echo "Building $(basename $file)"
            ./build.sh > /dev/null 2>&1
            cd -
        fi
    done
}