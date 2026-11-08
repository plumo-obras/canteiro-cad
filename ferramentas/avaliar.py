"""Compara o resultado do OCR com um gabarito extraído do texto vetorial do PDF original.
Uso: uv run python ferramentas/avaliar.py exemplos/2.pdf resultado/2.json  (o JSON sai de identificar-pranchas)"""

import json, re, sys
import fitz


def gabarito(pdf):
    linhas = [l.strip() for l in fitz.open(pdf)[0].get_text().splitlines() if l.strip()]
    vigas, buf, atual, pos_secao = {}, set(), None, False
    for i, l in enumerate(linhas):
        m = re.match(r"^(\d+)\s*N(\d+)\s*ø", l.replace("(1c) ", "").replace("(2c) ", ""))
        if m:
            n = int(m.group(2))
            (vigas[atual].add(n) if pos_secao and atual else buf.add(n))
        if l.startswith("RELAÇÃO") or l in ("ESC 1:25", "ESC 1:20"):
            buf = set()
        if l == "ESC 1:50" and i + 1 < len(linhas) and re.fullmatch(r"V\d+", linhas[i + 1]):
            atual = linhas[i + 1]
            vigas[atual] = set(buf)
            buf = set()
            pos_secao = False
        if l == "SEÇÃO A-A" and atual:
            pos_secao = True
        if re.fullmatch(r"V\d+", l) and i > 0 and linhas[i - 1] != "ESC 1:50" and pos_secao and l != atual:
            pass
        if l in ("0", "310") and pos_secao:
            pos_secao = False
    return vigas


g = gabarito(sys.argv[1])
r = json.load(open(sys.argv[2]))
obtido = {d["desenho"]: {a["n"] for a in d["armaduras"]} for d in r["detalhamentos"].get("Vigas", [])}
ok = acertos = total = extras = 0
for v in sorted(g, key=lambda v: int(v[1:])):
    esp, obt = g[v], obtido.get(v, set())
    acertos += len(esp & obt)
    total += len(esp)
    extras += len(obt - esp)
    flag = "OK " if esp == obt else "   "
    ok += esp == obt
    if esp != obt:
        print(f"{flag}{v}: faltam {sorted(esp - obt)} sobram {sorted(obt - esp)}")
print(f"Vigas perfeitas: {ok}/{len(g)} | barras encontradas {acertos}/{total} | barras atribuídas erradas {extras}")
