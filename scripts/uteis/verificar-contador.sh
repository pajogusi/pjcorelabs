#!/bin/bash

echo "== Verificar GoatCounter PJCore Labs =="

ERRO=0
CONTADOR="pjcorelabs.goatcounter.com/count"

while IFS= read -r ficheiro; do
    if ! grep -q "$CONTADOR" "$ficheiro"; then
        echo "FALTA CONTADOR: $ficheiro"
        ERRO=1
    else
        echo "OK: $ficheiro"
    fi
done < <(find website -name "*.html" | sort)

if [ "$ERRO" -ne 0 ]; then
    echo
    echo "Erro: há páginas HTML sem GoatCounter."
    exit 1
fi

echo
echo "Todas as páginas HTML têm GoatCounter."
