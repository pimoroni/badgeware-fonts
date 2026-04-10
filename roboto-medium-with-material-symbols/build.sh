SCRIPT_PATH=${BASH_SOURCE-$0}
SCRIPT_PATH=$(dirname "$SCRIPT_PATH")
SCRIPT_PATH=$(realpath "$SCRIPT_PATH")

mkdir -p $CI_BUILD_ROOT
$CI_PROJECT_ROOT/alright-fonts/afinate --quiet --font $SCRIPT_PATH/src/Roboto-Medium.ttf --icon-font $SCRIPT_PATH/src/MaterialSymbolsSharp_Filled-Regular.ttf --corpus symbols.txt --characters basic_latin --out $CI_BUILD_ROOT/Roboto-Medium-With-Material-Symbols.af
