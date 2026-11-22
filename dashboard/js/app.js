/* =====================================================================
   BRN Frotas — painel da brn-frota-data-platform
   ---------------------------------------------------------------------
   Lê window.DADOS (dados.js, gerado por pipeline/exportar_dashboard.py
   a partir das views da gold) e desenha as 4 abas em SVG/HTML puro,
   sem biblioteca externa. Todos os números respeitam os filtros.
   ===================================================================== */
"use strict";
const D = window.DADOS;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const nf = (v, d = 0) => v == null || isNaN(v) ? "–" : Number(v).toLocaleString("pt-BR", {minimumFractionDigits: d, maximumFractionDigits: d});
const pct = (v, d = 1) => v == null || !isFinite(v) ? "–" : nf(v * 100, d) + "%";
const brl = v => v == null ? "–" : "R$ " + (Math.abs(v) >= 1e6 ? nf(v / 1e6, 2) + " mi" : Math.abs(v) >= 1e4 ? nf(v / 1e3, 1) + " mil" : nf(v));
const brlCheio = v => v == null ? "–" : "R$ " + nf(v);
const sum = (a, f) => a.reduce((s, x) => s + (f ? f(x) : x || 0), 0);
const fmtD = iso => iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) : "–";
const fmtDA = iso => iso ? fmtD(iso) + "/" + iso.slice(0, 4) : "–";
const DSEM = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const dow = iso => new Date(iso + "T12:00:00").getDay();

/* ---------- dados em objetos (a exportação vem em listas compactas) ---------- */
const obj = (nome, linhas) => linhas.map(r => Object.fromEntries(D.colunas[nome].map((c, i) => [c, r[i]])));
const CC = obj("cc", D.cc), V = obj("veic", D.veic);
const USO = obj("uso", D.uso), SEMUSO = obj("sem_uso", D.sem_uso), AL = obj("alertas", D.alertas);
const OS = obj("os", D.os), COND = obj("conducao", D.conducao), PTS = obj("pontos", D.pontos);
const DIAS = D.dias, REF = D.meta.data_ref, IDX = Object.fromEntries(DIAS.map((d, i) => [d, i]));

const COR_REGRA = {"Excesso de velocidade": "var(--t0)", "Freada brusca": "var(--t1)", "Aceleração brusca": "var(--t2)",
                   "Curva brusca": "var(--tv)", "Motor ocioso": "var(--t3)"};
const ORDEM_REGRA = ["Excesso de velocidade", "Freada brusca", "Aceleração brusca", "Curva brusca", "Motor ocioso"];
const IR = Object.fromEntries(D.regras.map((r, i) => [r, i]));
// os 6 status da planilha de acompanhamento (Concluída fica fora da fila)
const ETAPAS = ["Em agendamento", "Em diagnóstico", "Aguardando aprovação", "Aguardando peças", "Em manutenção"];
const COR_ETAPA = {"Em agendamento": "var(--s0)", "Em diagnóstico": "var(--s4)", "Aguardando aprovação": "var(--s2)",
                   "Aguardando peças": "var(--s3)", "Em manutenção": "var(--s1)", "Concluída": "var(--s5)"};
const CRIT = {Alta: 0, "Média": 1, Baixa: 2};
// as 8 etapas do SLA da planilha: [nome, campo da OS, meta em dias]
const SLA = [["OS → Entrada na oficina", "d_os_entrada", 2], ["Entrada → Orçamento", "d_entrada_orcamento", 2],
             ["Orçamento → Solicitação", "d_orcamento_solicitacao", 1], ["Solicitação → Aprovação", "d_solicitacao_aprovacao", 2],
             ["Aprovação → Pedido de compra", "d_aprovacao_pedido", 1], ["Pedido → Compra efetivada", "d_pedido_compra", 2],
             ["Compra → Entrega da peça", "d_compra_entrega", 4], ["Entrada → Saída da oficina", "d_entrada_saida", 10]];
const FAIXAS = ["Suave", "Moderada", "Brusca", "Agressiva"];
const COR_FAIXA = ["var(--tv)", "var(--t0)", "var(--t3)", "var(--tred)"];

/* ---------------------------------- estado ---------------------------------- */
const S = {tab: "M", de: null, ate: null, reg: "", cc: "", tp: "", regra: null, etapa: "abertas", sortU: ["km", -1], buscaU: "", vistaU: "t"};
let xlsAtual = null;   // {nome, aba, titulo, cols: [{t, k, w, f}], linhas: [objetos]} da aba aberta

function veicOk(vi) { return !S.tp || V[vi].tipo === S.tp; }
function ccOk(ci) {
  if (S.cc) return String(ci) === S.cc;
  if (S.reg) return ci >= 0 && CC[ci].regional === S.reg;
  return true;
}
function diaOk(di) { return di >= S.de && di <= S.ate; }
function dataOk(iso) { return iso >= DIAS[S.de] && iso <= DIAS[S.ate]; }
const linhaOk = r => diaOk(r.dia) && veicOk(r.veic) && ccOk(r.cc);

/* -------------------------------- auxiliares -------------------------------- */
const tip = $("tip");
document.addEventListener("mousemove", e => {
  const t = e.target.closest("[data-tip]");
  if (!t) { tip.style.display = "none"; return; }
  tip.innerHTML = t.getAttribute("data-tip");
  tip.style.display = "block";
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - w - 8) + "px";
  tip.style.top = (e.clientY + 16 + h > innerHeight ? e.clientY - h - 10 : e.clientY + 16) + "px";
});

function ring(p, c) {
  const r = 21, C = 2 * Math.PI * r, v = Math.max(0, Math.min(1, p || 0));
  return `<svg class="rg" viewBox="0 0 56 56" aria-hidden="true"><circle cx="28" cy="28" r="${r}" fill="none" stroke="var(--line)" stroke-width="6"/><circle cx="28" cy="28" r="${r}" fill="none" stroke="${c}" stroke-width="6" stroke-linecap="round" stroke-dasharray="${(C * v).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 28 28)"/><text x="28" y="32.5" text-anchor="middle">${p == null ? "–" : nf(p * 100, p < .1 && p > 0 ? 1 : 0) + "%"}</text></svg>`;
}
function spark(a, c, cls = "spk") {
  if (!a || a.length < 2) return "";
  const W = 200, H = 40, mx = Math.max(...a, 1e-9), mn = Math.min(...a, 0), sc = v => H - 3 - (H - 8) * (v - mn) / ((mx - mn) || 1);
  const d = "M" + a.map((v, i) => (i * W / (a.length - 1)).toFixed(1) + "," + sc(v).toFixed(1)).join(" L");
  return `<svg class="${cls}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path d="${d} L${W},${H} L0,${H} Z" fill="${c}" fill-opacity=".14"/><path d="${d}" fill="none" stroke="${c}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}
function rkCards(id, cards) {
  $(id).innerHTML = cards.map(k => `<div class="rk" style="--c:${k.c}"><div class="rt"><div><span class="l">${k.l}</span><b>${k.v}</b></div>${ring(k.p, k.c)}</div><div class="s">${k.s || ""}</div>${spark(k.sr, k.c)}<div class="sl">${k.sl || ""}</div></div>`).join("");
}
function kpis(id, K) {
  $(id).innerHTML = K.map(k => `<div class="k"><span>${k[0]}</span><b>${k[1]}</b><small>${k[2] || ""}</small></div>`).join("");
}
/* barras horizontais (estilo .mbar do modelo): {k, v, lab, sub, r (referência cinza), meta, cls, c, tip} */
function mbar(id, items, opt = {}) {
  if (!items.length) { $(id).innerHTML = `<div class="empty">Sem dados no filtro.</div>`; return; }
  const mx = opt.max || Math.max(...items.map(i => Math.max(i.v || 0, i.r || 0, i.meta || 0)), 1e-9);
  const sc = v => Math.max(0, Math.min(100, 100 * v / mx));
  $(id).innerHTML = `<div class="mbar">` + items.map(i => `<div class="n" title="${esc(i.k)}">${esc(i.k)}</div><div class="t"${i.tip ? ` data-tip="${esc(i.tip)}"` : ""}>${i.r != null ? `<i class="r" style="width:${sc(i.r)}%"></i>` : ""}<i class="${i.cls || "c"}" style="width:${Math.max(i.v > 0 ? 1 : 0, sc(i.v))}%;${i.c ? `--c:${i.c}` : ""}"></i>${i.meta != null ? `<em style="left:calc(${sc(i.meta)}% - 1px)"></em>` : ""}</div><div class="v ${i.vc || ""}">${i.lab}${i.sub ? `<small>${i.sub}</small>` : ""}</div>`).join("") + `</div>`;
}
const tick = mx => { const p = Math.pow(10, Math.floor(Math.log10(mx || 1))), n = mx / p; return (n <= 2 ? .5 : n <= 5 ? 1 : 2) * p; };
const curto = v => v >= 1e6 ? nf(v / 1e6, 1) + " mi" : v >= 1e3 ? nf(v / 1e3, v >= 1e4 ? 0 : 1) + " mil" : nf(v);
/* barras verticais empilhadas: labels[], series[{nome, cor, vals[]}], opções {fmt, marcar(i), passo} */
function barras(id, labels, series, o = {}) {
  const W = o.w || 1000, H = o.h || 240, L = 46, B = 24, T = 10, n = labels.length;
  if (!n) { $(id).innerHTML = `<div class="empty">Sem dados no filtro.</div>`; return; }
  const tot = labels.map((_, i) => sum(series, s => s.vals[i] || 0)), mx = Math.max(...tot, 1e-9), tk = tick(mx), top = Math.ceil(mx / tk) * tk;
  const bw = (W - L - 6) / n, y = v => T + (H - T - B) * (1 - v / top), fmt = o.fmt || nf;
  let g = "";
  for (let v = 0; v <= top + 1e-9; v += tk) g += `<line class="gl" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${curto(v)}</text>`;
  const passo = o.passo || Math.ceil(n / 14);
  labels.forEach((lb, i) => {
    const x = L + 3 + i * bw; let acc = 0;
    if (o.marcar && o.marcar(i)) g += `<rect x="${x}" y="${T}" width="${bw}" height="${H - T - B}" fill="var(--line)" opacity=".35"/>`;
    const det = series.filter(s => s.vals[i]).map(s => `<span style="color:${s.cor}">■</span> ${esc(s.nome)}: ${fmt(s.vals[i])}`).join("<br>");
    series.forEach(s => {
      const v = s.vals[i] || 0; if (!v) return;
      g += `<rect x="${(x + bw * .12).toFixed(1)}" y="${y(acc + v).toFixed(1)}" width="${(bw * .76).toFixed(1)}" height="${(y(acc) - y(acc + v)).toFixed(1)}" style="fill:${s.cor}"/>`;
      acc += v;
    });
    const dica = `<b>${esc(o.tipLabel ? o.tipLabel(i) : lb)}</b>${series.length > 1 ? det + "<br>" : ""}Total: ${fmt(tot[i])}`;
    g += `<rect class="hit" x="${x}" y="${T}" width="${bw}" height="${H - T - B}" data-tip="${esc(dica)}"/>`;
    if (i % passo === 0) g += `<text class="ax" x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(lb)}</text>`;
  });
  $(id).innerHTML = `<svg class="ch" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
}
function legenda(id, nomes, ativo, onClick, cores = COR_REGRA) {
  $(id).innerHTML = nomes.map(n => `<button type="button" class="lgb ${ativo === n ? "on" : ativo ? "off" : ""}" data-n="${esc(n)}" style="--c:${cores[n]}"><span class="d"></span>${esc(n)}</button>`).join("");
  if (onClick) $(id).querySelectorAll(".lgb").forEach(b => b.onclick = () => onClick(b.dataset.n));
}
function tabela(id, cols, linhas, sortState, onSort) {
  const cab = cols.map(c => `<th class="${c.n ? "n" : ""}" data-c="${c.k}">${c.t}${sortState && sortState[0] === c.k ? (sortState[1] < 0 ? " ▼" : " ▲") : ""}</th>`).join("");
  $(id).innerHTML = `<thead><tr>${cab}</tr></thead><tbody>` + (linhas.length ? linhas.map(r => `<tr>${cols.map(c => `<td class="${c.n ? "n" : ""} ${c.cls || ""}">${c.f ? c.f(r) : esc(r[c.k])}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${cols.length}" class="empty">Nada neste filtro.</td></tr>`) + `</tbody>`;
  if (onSort) $(id).querySelectorAll("th").forEach(th => th.onclick = () => onSort(th.dataset.c));
}
const placaCel = vi => placaBtn(vi);
const ccNome = ci => ci >= 0 ? CC[ci].centro_custo : "–";
const meses = () => { const m = []; for (let i = S.de; i <= S.ate; i++) { const k = DIAS[i].slice(0, 7); if (!m.includes(k)) m.push(k); } return m; };
const NMES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const nomeMes = k => NMES[+k.slice(5, 7) - 1] + "/" + k.slice(2, 4);


/* ------------------------------ mapa do Brasil ------------------------------ */
// Coordenadas das capitais usadas como centros de custo (as cidades são reais; veículos, placas e motoristas não).
const COORD = {"Belém": [-1.46, -48.49], "Manaus": [-3.12, -60.02], "Fortaleza": [-3.73, -38.52], "Recife": [-8.05, -34.88],
  "Salvador": [-12.97, -38.50], "Brasília": [-15.79, -47.88], "Goiânia": [-16.68, -49.25], "São Paulo": [-23.55, -46.63],
  "Rio de Janeiro": [-22.91, -43.17], "Belo Horizonte": [-19.92, -43.94], "Curitiba": [-25.43, -49.27], "Porto Alegre": [-30.03, -51.23]};
const ROTULO_ESQ = new Set(["Goiânia", "São Paulo", "Manaus", "Curitiba", "Porto Alegre"]);
const REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"];
function projetar(lat, lon) {
  const P = window.MAPA_BR.proj, merc = l => Math.log(Math.tan(Math.PI / 4 + l * Math.PI / 360));
  return [(lon - P.oeste) / (P.leste - P.oeste) * P.largura + P.margem,
          (merc(P.norte) - merc(lat)) / (merc(P.norte) - merc(P.sul)) * P.altura + P.margem];
}
/* cidades: [{cidade, v, lab, tip}]; regioes: {Norte: {v, lab}}; cor: cor da bolha */
function mapaBrasil(id, cidades, regioes, cor, titulo, faixa = false) {
  if (!window.MAPA_BR) { $(id).innerHTML = `<div class="empty">mapa_brasil.js não carregado.</div>`; return; }
  const vr = REGIOES.map(r => regioes[r]?.v || 0), mxR = Math.max(...vr, 1e-9), mnR = faixa ? Math.min(...vr.filter(v => v > 0), mxR) : 0;
  const mxC = Math.max(...cidades.map(c => c.v), 1e-9), mnC = faixa ? Math.min(...cidades.map(c => c.v), mxC) : 0;
  let g = window.MAPA_BR.estados.map(([uf, nome, reg, d]) => {
    const v = regioes[reg]?.v || 0, o = v ? Math.round(8 + 32 * (v - mnR) / ((mxR - mnR) || 1)) : 4, sel = S.reg && S.reg !== reg;
    return `<path class="uf${sel ? " off" : ""}" data-reg="${reg}" d="${d}" style="fill:color-mix(in srgb,${cor} ${o}%,var(--card))" data-tip="${esc(`<b>${reg}</b>${nome}<br>${titulo}: ${regioes[reg]?.lab ?? "–"}<br><i>clique para filtrar a região</i>`)}"/>`;
  }).join("");
  cidades.filter(c => COORD[c.cidade]).sort((a, b) => b.v - a.v).forEach(c => {
    const [x, y] = projetar(...COORD[c.cidade]), r = faixa ? 6 + 18 * (c.v - mnC) / ((mxC - mnC) || 1) : 4 + 22 * Math.sqrt(c.v / mxC), esq = ROTULO_ESQ.has(c.cidade);
    g += `<circle class="bolha" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" style="fill:${cor}" data-tip="${esc(c.tip)}"/>`;
    g += `<text class="cid" x="${(x + (esq ? -r - 4 : r + 4)).toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="${esq ? "end" : "start"}">${esc(c.cidade)} <tspan>${c.lab}</tspan></text>`;
  });
  $(id).innerHTML = `<svg class="ch mapa" viewBox="-10 0 720 645" role="img" aria-label="Mapa do Brasil">${g}</svg>` +
    `<div class="mreg">${REGIOES.map(r => `<button type="button" class="chip ${S.reg === r ? "on" : ""}" data-reg="${r}" style="--c:${cor}"><b>${regioes[r]?.lab ?? "–"}</b>${r}</button>`).join("")}</div>`;
  $(id).querySelectorAll("[data-reg]").forEach(el => el.onclick = () => filtrarRegiao(el.dataset.reg));
}
function filtrarRegiao(reg) {
  S.reg = S.reg === reg ? "" : reg; S.cc = "";
  $("fReg").value = S.reg; opcoesCC(); render();
}

/* ================================ MANUTENÇÃO ================================ */
function abaM() {
  const osF = OS.filter(o => veicOk(o.veic) && ccOk(o.cc));
  const abertas = osF.filter(o => !o.saida);
  const noPer = osF.filter(o => dataOk(o.data_os));
  const frota = V.filter((v, i) => veicOk(i) && ccOk(v.cc_atual)).length;
  const veicAbertos = new Set(abertas.map(o => o.veic)).size;
  const parados = abertas.filter(o => o.status_operacional === "Parado");
  const atrasadas = abertas.filter(o => o.atrasada);
  const saidas = noPer.filter(o => o.saida);
  const comPrev = saidas.filter(o => o.prevista), noPrazo = comPrev.filter(o => o.saida <= o.prevista);
  const reinc = noPer.filter(o => o.reincidente);
  const orc = sum(noPer.filter(o => o.negociado != null), o => o.orcado || 0), lib = sum(noPer, o => o.negociado || 0);

  // série: OS abertas em cada dia do período (entrada <= dia < saída)
  const dd = []; for (let i = S.de; i <= S.ate; i++) dd.push(DIAS[i]);
  const passo = Math.max(1, Math.floor(dd.length / 40)), amostra = dd.filter((_, i) => i % passo === 0);
  const abertasNoDia = amostra.map(d => osF.filter(o => o.entrada <= d && (!o.saida || o.saida > d)).length);
  const paradosNoDia = amostra.map(d => osF.filter(o => o.entrada <= d && (!o.saida || o.saida > d) && o.status_operacional === "Parado").length);
  const atrasNoDia = amostra.map(d => osF.filter(o => o.prevista < d && (!o.saida || o.saida > d) && o.entrada <= d).length);
  const semanas = []; for (let i = 0; i < dd.length; i += 7) semanas.push(dd.slice(i, i + 7));
  const saidasSem = semanas.map(w => osF.filter(o => o.saida && o.saida >= w[0] && o.saida <= w[w.length - 1]).length);
  const reincSem = semanas.map(w => osF.filter(o => o.reincidente && o.data_os >= w[0] && o.data_os <= w[w.length - 1]).length);
  const econSem = semanas.map(w => sum(osF.filter(o => o.data_os >= w[0] && o.data_os <= w[w.length - 1]), o => (o.orcado || 0) - (o.negociado || 0)));
  const desde = "desde " + fmtD(DIAS[S.de]);

  rkCards("mK", [
    {l: "Em manutenção", v: nf(veicAbertos), p: frota ? veicAbertos / frota : 0, c: "var(--tred)", s: `${pct(frota ? veicAbertos / frota : 0)} da frota · ${abertas.length} OS abertas`, sr: abertasNoDia, sl: "OS abertas, dia a dia " + desde},
    {l: "Parados", v: nf(new Set(parados.map(o => o.veic)).size), p: veicAbertos ? new Set(parados.map(o => o.veic)).size / veicAbertos : 0, c: "var(--t3)", s: `dos veículos em manutenção · ${abertas.filter(o => o.status_operacional === "Restrição").length} OS rodando com restrição`, sr: paradosNoDia, sl: "parados na oficina, dia a dia " + desde},
    {l: "Atrasadas", v: nf(atrasadas.length), p: abertas.length ? atrasadas.length / abertas.length : 0, c: "var(--tred)", s: "OS abertas que passaram da data prevista de saída", sr: atrasNoDia, sl: "atrasos acumulados, dia a dia " + desde},
    {l: "Entregues no período", v: nf(saidas.length), p: comPrev.length ? noPrazo.length / comPrev.length : null, c: "var(--tv)", s: `${noPrazo.length} de ${comPrev.length} com previsão saíram no prazo`, sr: saidasSem, sl: "saídas por semana " + desde},
    {l: "Reincidências", v: nf(reinc.length), p: noPer.length ? reinc.length / noPer.length : 0, c: "var(--t1)", s: "mesmo veículo e sistema em até 90 dias (sem preventiva)", sr: reincSem, sl: "reincidências por semana " + desde},
    {l: "Economia na negociação", v: brl(orc - lib), p: orc ? (orc - lib) / orc : 0, c: "var(--t0)", s: `orçado ${brl(orc)} → negociado ${brl(lib)}`, sr: econSem, sl: "orçado − negociado, por semana " + desde},
  ]);

  // funil: etapa atual das OS abertas
  const porEtapa = ETAPAS.map(e => ({e, n: abertas.filter(o => o.etapa === e).length}));
  mbar("mFun", porEtapa.map(x => ({k: x.e, v: x.n, cls: "s", c: COR_ETAPA[x.e], lab: nf(x.n), sub: pct(abertas.length ? x.n / abertas.length : 0),
    tip: `<b>${x.e}</b>${x.n} OS · média de ${nf(sum(abertas.filter(o => o.etapa === x.e), o => (new Date(REF) - new Date(o.data_os)) / 864e5) / (x.n || 1), 1)} dias desde a abertura`})));

  // SLA: média por etapa x meta
  mbar("mSla", SLA.map(([nome, col, meta]) => {
    const vs = noPer.map(o => o[col]).filter(v => v != null).sort((a, b) => a - b);
    const med = vs.length ? sum(vs) / vs.length : 0, p90 = vs.length ? vs[Math.min(vs.length - 1, Math.floor(.9 * (vs.length - 1) + .5))] : null;
    const dentro = vs.filter(v => v <= meta).length;
    return {k: nome, v: med, meta, cls: med > meta ? "b" : "g", lab: nf(med, 1) + " d", vc: med > meta ? "neg" : "",
            sub: `meta ${meta} d · ${vs.length} OS`, tip: `<b>${nome}</b>média ${nf(med, 1)} d · p90 ${nf(p90)} d<br>${pct(vs.length ? dentro / vs.length : 0, 0)} dentro da meta de ${meta} d`};
  }), {max: Math.max(...SLA.map(s => s[2] * 1.6), ...SLA.map(([, col]) => { const vs = noPer.map(o => o[col]).filter(v => v != null); return vs.length ? sum(vs) / vs.length * 1.1 : 0; }))});

  // fila priorizada
  const chips = [["abertas", "Em aberto", abertas.length], ["atrasadas", "Atrasadas", atrasadas.length]]
    .concat(ETAPAS.map(e => [e, e, abertas.filter(o => o.etapa === e).length]));
  $("mChips").innerHTML = chips.map(([k, t, n]) => `<button type="button" class="chip ${S.etapa === k ? "on" : ""}" data-k="${esc(k)}" style="--c:${COR_ETAPA[k] || "var(--orange)"}"><b>${n}</b>${esc(t)}</button>`).join("");
  $("mChips").querySelectorAll(".chip").forEach(b => b.onclick = () => { S.etapa = b.dataset.k; abaM(); });
  const fila = abertas.filter(o => S.etapa === "abertas" || (S.etapa === "atrasadas" ? o.atrasada : o.etapa === S.etapa))
    .sort((a, b) => (b.atrasada - a.atrasada) || (CRIT[a.criticidade] - CRIT[b.criticidade]) || (b.dias_parado - a.dias_parado));
  $("mFilaAs").textContent = `${fila.length} OS`;
  const pillCrit = c => `<span class="pill ${c === "Alta" ? "bad" : c === "Média" ? "mid" : "gray"}">${c}</span>`;
  const atraso = o => o.atrasada ? `<span class="pill bad">${(new Date(REF) - new Date(o.prevista)) / 864e5} d atraso</span>` : "";
  const colsFila = [
    {k: "numero_os", t: "OS", f: o => `<span class="sm">${o.numero_os}</span>`},
    {k: "placa", t: "Placa", f: o => placaCel(o.veic)},
    {k: "cc", t: "Centro de custo", f: o => esc(ccNome(o.cc))},
    {k: "oficina", t: "Oficina"},
    {k: "tipo_sistema", t: "Sistema", f: o => `${esc(o.tipo_sistema)}<div class="sm">${esc(o.tipo_manutencao)}</div>`},
    {k: "etapa", t: "Etapa", f: o => `<span class="pill" style="--c:${COR_ETAPA[o.etapa]}">${o.etapa}</span>`},
    {k: "criticidade", t: "Criticidade", f: o => pillCrit(o.criticidade)},
    {k: "dias_parado", t: "Dias parado", n: 1, f: o => o.dias_parado ?? "–"},
    {k: "prevista", t: "Previsão", f: o => fmtD(o.prevista) + " " + atraso(o)},
    {k: "orcado", t: "Orçado", n: 1, f: o => brlCheio(o.orcado)},
    {k: "status_operacional", t: "Situação", f: o => `<span class="pill ${o.status_operacional === "Parado" ? "bad" : o.status_operacional === "Operando" ? "ok" : "mid"}">${o.status_operacional}</span>`},
    {k: "substituto", t: "Substituto", f: o => o.substituto ? `<span class="mono">${esc(o.placa_substituto || "sem placa")}</span><div class="sm">${esc(o.tipo_aluguel || "")}</div>` : "—"},
  ];
  tabela("mFila", colsFila, fila);
  xlsAtual = {nome: "fila_manutencao", aba: "Fila de manutenção", titulo: "Fila priorizada de manutenção (OS abertas)",
    cols: [{t: "OS", k: "numero_os", w: 13}, {t: "Placa", k: "placa", w: 10}, {t: "Modelo", k: "modelo", w: 22}, {t: "Centro de custo", k: "cc_nome", w: 18},
           {t: "Contrato", k: "contrato", w: 12}, {t: "Oficina", k: "oficina", w: 16}, {t: "Sistema", k: "tipo_sistema", w: 14}, {t: "Tipo", k: "tipo_manutencao", w: 11},
           {t: "Etapa", k: "etapa", w: 20}, {t: "Criticidade", k: "criticidade", w: 11}, {t: "Abertura", k: "data_os", w: 11, f: "data"},
           {t: "Entrada", k: "entrada", w: 11, f: "data"}, {t: "Previsão de saída", k: "prevista", w: 11, f: "data"}, {t: "Dias parado", k: "dias_parado", w: 9, f: "int"},
           {t: "Atrasada", k: "atrasada_txt", w: 9}, {t: "Orçado", k: "orcado", w: 13, f: "brl"}, {t: "Nº requisição", k: "requisicao", w: 13},
           {t: "Situação", k: "status_operacional", w: 11}, {t: "Substituto", k: "placa_substituto", w: 11}, {t: "Custo total até agora", k: "custo_total", w: 14, f: "brl"}],
    linhas: fila.map(o => ({...o, placa: V[o.veic].placa, modelo: V[o.veic].modelo, cc_nome: ccNome(o.cc), atrasada_txt: o.atrasada ? "sim" : "não"}))};

  // custo por sistema e oficina
  const grupo = (lista, campo) => {
    const m = {}; lista.filter(o => o.negociado != null).forEach(o => { const g = m[o[campo]] ||= {k: o[campo], orc: 0, lib: 0, n: 0}; g.orc += o.orcado || 0; g.lib += o.negociado || 0; g.n++; });
    return Object.values(m).sort((a, b) => b.lib - a.lib || b.orc - a.orc);
  };
  mbar("mSis", grupo(noPer, "tipo_sistema").map(g => ({k: g.k, v: g.lib, r: g.orc, lab: brl(g.lib), sub: `${g.n} OS`, tip: `<b>${esc(g.k)}</b>orçado ${brlCheio(g.orc)}<br>negociado ${brlCheio(g.lib)}`})));
  mbar("mOfi", grupo(noPer, "oficina").map(g => {
    const d = g.orc ? (g.lib - g.orc) / g.orc : 0;
    return {k: g.k, v: g.lib, r: g.orc, lab: (d <= 0 ? "" : "+") + pct(d), vc: d < -.15 ? "neg" : "", sub: `${brl(g.lib)} · ${g.n} OS`, tip: `<b>${esc(g.k)}</b>orçado ${brlCheio(g.orc)} → negociado ${brlCheio(g.lib)}`};
  }));

  // reincidências
  const re = noPer.filter(o => o.reincidente).sort((a, b) => b.data_os.localeCompare(a.data_os)).slice(0, 8);
  $("mRe").innerHTML = re.length ? re.map(o => {
    const ant = OS.filter(x => x.veic === o.veic && x.tipo_sistema === o.tipo_sistema && x.data_os < o.data_os).sort((a, b) => b.data_os.localeCompare(a.data_os))[0];
    const dias = ant ? Math.round((new Date(o.data_os) - new Date(ant.data_os)) / 864e5) : null;
    return `<div class="apt" style="--c:var(--t1)"><div class="h"><b class="pl clk" data-v="${o.veic}"><span class="pt">${esc(V[o.veic].placa)}</span></b><em>${dias ?? "–"} d</em></div><p><b>${esc(o.tipo_sistema)}</b> de novo. ${ant ? `Antes: ${fmtD(ant.data_os)} na ${esc(ant.oficina)} (${esc(ant.descricao)}).` : ""} Agora: ${esc(o.descricao)} · ${esc(o.oficina)}.</p><p class="m">${o.numero_os} · ${esc(ccNome(o.cc))}</p></div>`;
  }).join("") : `<div class="empty">Nenhuma reincidência no período.</div>`;

  // idade da frota (do mais velho para o mais novo)
  const vis = V.map((v, vi) => vi).filter(vi => veicOk(vi) && ccOk(V[vi].cc_atual));
  const idades = vis.filter(vi => V[vi].ano).map(vi => ({vi, idade: idadeVeic(V[vi])})).sort((a, b) => b.idade - a.idade);
  const corIdade = i => i >= 8 ? "var(--t1)" : i >= 4 ? "var(--t3)" : "var(--ink3)";
  $("mIdSub").textContent = idades.length ? `média ${nf(sum(idades, x => x.idade) / idades.length, 1)} anos · ${idades.filter(x => x.idade >= 8).length} com 8 anos ou mais · ${idades.filter(x => x.idade <= 3).length} com até 3 anos` : "";
  $("mIdLg").innerHTML = [["8 anos ou mais", "var(--t1)"], ["4 a 7 anos", "var(--t3)"], ["até 3 anos", "var(--ink3)"]].map(([t, c]) => `<span class="lgb" style="--c:${c}"><span class="d"></span>${t}</span>`).join("");
  linhasVeic("mIdade", idades.slice(0, 15).map(x => ({vi: x.vi, v: x.idade, lab: `${x.idade} anos`, sub: `(${V[x.vi].ano})`, c: corIdade(x.idade)})), Math.max(1, ...idades.map(x => x.idade)));

  // dias desde a última manutenção concluída
  const ult = vis.map(vi => ({vi, d: V[vi].dias_desde_ultima})).filter(x => x.d != null).sort((a, b) => b.d - a.d);
  const semManut = vis.filter(vi => V[vi].dias_desde_ultima == null).length;
  const corUlt = d => d > 180 ? "var(--tred)" : d > 90 ? "var(--t3)" : "var(--tv)";
  $("mUltSub").textContent = `${ult.filter(x => x.d <= 90).length} até 90 dias · ${ult.filter(x => x.d > 90 && x.d <= 180).length} de 91 a 180 · ${ult.filter(x => x.d > 180).length} acima de 180 · ${semManut} sem manutenção registrada no período simulado`;
  $("mUltLg").innerHTML = [["até 90 dias", "var(--tv)"], ["91 a 180 dias", "var(--t3)"], ["mais de 180 dias", "var(--tred)"]].map(([t, c]) => `<span class="lgb" style="--c:${c}"><span class="d"></span>${t}</span>`).join("");
  linhasVeic("mUlt", ult.slice(0, 15).map(x => ({vi: x.vi, v: x.d, lab: `há ${nf(x.d)} dias`, sub: fmtDA(V[x.vi].ultima_data), c: corUlt(x.d)})), Math.max(1, ...ult.map(x => x.d)));

  // condução x corretiva: custo corretivo médio por faixa de condução (view gold.vw_conducao_faixas)
  const pts = COND.filter(c => veicOk(c.veic) && ccOk(V[c.veic].cc_atual));
  const fx = FAIXAS.map((nome, i) => {
    const g = pts.filter(p => p.faixa === i + 1);
    return {nome, n: g.length, custo: g.length ? sum(g, p => p.custo_corretivo) / g.length : 0,
            corr: g.length ? sum(g, p => p.corretivas) / g.length : 0, taxa: g.length ? sum(g, p => p.bruscos_100km) / g.length : 0};
  });
  const suave = fx[0].custo, agr = fx[3].custo;
  $("mCorrT").textContent = "Quem dirige pior gasta mais com corretiva";
  $("mCorrAs").textContent = `correlação r = ${nf(pearson(pts.map(p => p.bruscos_100km), pts.map(p => p.custo_corretivo)), 2)}`;
  $("mCorrSub").innerHTML = `${agr > 0 ? `Faixa agressiva: <b>${brl(agr)}</b> de corretiva por veículo, contra <b>${brl(fx[1].custo)}</b> na moderada e <b>${brl(suave)}</b> na suave. ` : ""}Custo corretivo médio por veículo em cada faixa de condução (alertas de freada, aceleração e curva bruscas a cada 100 km; veículos com 500 km ou mais). Na frota toda, CORR() dá <b>r = ${nf(D.corr[2], 2)}</b>.`;
  barras("mCorr", fx.map(f => `${f.nome} (${f.n})`), fx.map((f, i) => ({nome: f.nome, cor: COR_FAIXA[i], vals: fx.map((_, j) => j === i ? Math.round(f.custo) : 0)})),
    {w: 600, h: 250, passo: 1, fmt: brlCheio, tipLabel: i => `${fx[i].nome}: ${fx[i].n} veículos · ${nf(fx[i].taxa, 1)} alertas/100 km · ${nf(fx[i].corr, 1)} corretivas por veículo`});
}
/* linhas por veículo com barra (idade, dias desde a manutenção) — clique abre o painel do veículo */
function linhasVeic(id, itens, max) {
  $(id).innerHTML = itens.length ? `<div class="vlist">${itens.map(x => `<div class="vl" data-v="${x.vi}">
    <span class="p"><b>${esc(V[x.vi].placa)}</b> <small>${esc(V[x.vi].modelo)}</small></span>
    <span class="t"><i style="width:${Math.max(2, 100 * x.v / max)}%;background:${x.c}"></i></span>
    <span class="n"><b>${x.lab}</b> <small>${x.sub}</small></span></div>`).join("")}</div>` : `<div class="empty">Sem veículos no filtro.</div>`;
}
function pearson(x, y) {
  const n = x.length; if (n < 3) return null;
  const mx = sum(x) / n, my = sum(y) / n; let a = 0, b = 0, c = 0;
  for (let i = 0; i < n; i++) { a += (x[i] - mx) * (y[i] - my); b += (x[i] - mx) ** 2; c += (y[i] - my) ** 2; }
  return b && c ? a / Math.sqrt(b * c) : null;
}

/* ================================ UTILIZAÇÃO ================================ */
function abaU() {
  const u = USO.filter(linhaOk);
  const km = sum(u, r => r.km), hu = sum(u, r => r.horas_uso), ho = sum(u, r => r.horas_ocioso), vg = sum(u, r => r.viagens), cons = sum(u, r => r.consumo_l);
  const vds = new Set(u.map(r => r.veic + "|" + r.dia)).size, veics = new Set(u.map(r => r.veic)).size;
  const su = SEMUSO.filter(linhaOk);
  const comRast = V.filter((v, i) => v.rastreador && veicOk(i) && ccOk(v.cc_atual)).length;
  kpis("uK", [
    ["Veículos com uso", nf(veics), `de ${comRast} com rastreador no filtro`],
    ["Viagens", nf(vg), `${nf(vg / (S.ate - S.de + 1), 0)} por dia`],
    ["Km rodados", nf(km), `${nf(cons)} L de combustível`],
    ["Horas de motor ligado", nf(hu) + " h", `${nf(km / (cons || 1), 1)} km/L na média`],
    ["Tempo ligado parado", pct(hu ? ho / hu : 0), `${nf(ho)} h de motor ocioso`],
    ["Km por veículo-dia", nf(vds ? km / vds : 0, 1), `${nf(vds)} veículo-dias com viagem`],
  ]);

  // km por dia
  const lab = [], vals = [];
  for (let i = S.de; i <= S.ate; i++) { lab.push(fmtD(DIAS[i])); vals.push(0); }
  u.forEach(r => vals[r.dia - S.de] += r.km);
  barras("uDia", lab, [{nome: "Km", cor: "var(--own)", vals: vals.map(v => Math.round(v))}],
    {marcar: i => [0, 6].includes(dow(DIAS[S.de + i])), tipLabel: i => DSEM[dow(DIAS[S.de + i])] + " " + fmtDA(DIAS[S.de + i]), fmt: v => nf(v) + " km"});

  // por centro de custo
  const pc = {}; u.forEach(r => { const g = pc[r.cc] ||= {km: 0, hu: 0, ho: 0}; g.km += r.km; g.hu += r.horas_uso; g.ho += r.horas_ocioso; });
  const lcc = Object.entries(pc).map(([ci, g]) => ({k: ccNome(+ci), ...g}));
  const kmReg = {}; Object.entries(pc).forEach(([ci, g]) => { if (+ci < 0) return; const r = kmReg[CC[ci].regional] ||= {v: 0}; r.v += g.km; });
  Object.values(kmReg).forEach(r => r.lab = curto(r.v) + " km");
  mapaBrasil("uCC", Object.entries(pc).filter(([ci]) => +ci >= 0).map(([ci, g]) => ({cidade: CC[ci].cidade, v: g.km, lab: curto(g.km),
    tip: `<b>${esc(CC[ci].cidade)}</b>${esc(CC[ci].centro_custo)} · ${CC[ci].regional}<br>${nf(g.km)} km · ${pct(km ? g.km / km : 0)} do total<br>${nf(g.hu)} h de motor ligado`})), kmReg, "var(--own)", "km rodados");
  mbar("uOc", lcc.map(g => ({...g, p: g.hu ? g.ho / g.hu : 0})).sort((a, b) => b.p - a.p).map(g => ({k: g.k, v: g.p, lab: pct(g.p), sub: nf(g.ho) + " h ociosas"})));

  // km por dia da semana (média)
  const ks = Array(7).fill(0), ns = Array(7).fill(0);
  for (let i = S.de; i <= S.ate; i++) ns[dow(DIAS[i])]++;
  u.forEach(r => ks[dow(DIAS[r.dia])] += r.km);
  const ord = [1, 2, 3, 4, 5, 6, 0];
  barras("uSem", ord.map(d => DSEM[d]), [{nome: "Km/dia", cor: "var(--own)", vals: ord.map(d => Math.round(ns[d] ? ks[d] / ns[d] : 0))}], {w: 520, h: 230, passo: 1, fmt: v => nf(v) + " km/dia"});

  // dias sem uso por veículo
  const sv = {}; su.forEach(r => sv[r.veic] = (sv[r.veic] || 0) + 1);
  const ndias = S.ate - S.de + 1;
  mbar("uSemUso", Object.entries(sv).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([vi, n]) => ({k: V[vi].placa + " · " + V[vi].tipo, v: n, max: ndias, lab: nf(n) + " d", sub: pct(n / ndias, 0) + " do período", cls: "s", c: n / ndias > .5 ? "var(--tred)" : "var(--t3)"})), {max: ndias});

  // tabela por veículo
  const pv = {};
  u.forEach(r => { const g = pv[r.veic] ||= {veic: r.veic, viagens: 0, km: 0, hu: 0, ho: 0, l: 0, dias: new Set(), vmax: 0}; g.viagens += r.viagens; g.km += r.km; g.hu += r.horas_uso; g.ho += r.horas_ocioso; g.l += r.consumo_l; g.dias.add(r.dia); g.vmax = Math.max(g.vmax, r.vel_maxima || 0); });
  let linhas = Object.values(pv).map(g => ({...g, placa: V[g.veic].placa, modelo: V[g.veic].modelo, tipo: V[g.veic].tipo, cc: ccNome(V[g.veic].cc_atual), ndias: g.dias.size, ocioso: g.hu ? g.ho / g.hu : 0, kml: g.l ? g.km / g.l : null, semuso: sv[g.veic] || 0}));
  const b = S.buscaU.toLowerCase();
  if (b) linhas = linhas.filter(l => (l.placa + " " + l.modelo + " " + l.cc + " " + l.tipo).toLowerCase().includes(b));
  const [sk, sd] = S.sortU;
  linhas.sort((x, y) => (typeof x[sk] === "string" ? x[sk].localeCompare(y[sk]) : (x[sk] ?? -1) - (y[sk] ?? -1)) * sd);
  const cols = [
    {k: "placa", t: "Placa", f: l => placaBtn(l.veic, false)}, {k: "modelo", t: "Modelo"}, {k: "tipo", t: "Tipo"}, {k: "cc", t: "Centro de custo atual"},
    {k: "viagens", t: "Viagens", n: 1, f: l => nf(l.viagens)}, {k: "km", t: "Km", n: 1, f: l => nf(l.km)}, {k: "hu", t: "Horas ligado", n: 1, f: l => nf(l.hu)},
    {k: "ocioso", t: "% ocioso", n: 1, f: l => pct(l.ocioso)}, {k: "kml", t: "Km/L", n: 1, f: l => nf(l.kml, 1)},
    {k: "ndias", t: "Dias com uso", n: 1}, {k: "semuso", t: "Dias sem uso", n: 1}, {k: "vmax", t: "Vel. máx.", n: 1, f: l => nf(l.vmax)},
  ];
  tabela("uTab", cols, linhas, S.sortU, k => { S.sortU = [k, S.sortU[0] === k ? -S.sortU[1] : -1]; abaU(); });
  $("uTabWrap").hidden = S.vistaU !== "t"; $("uGal").hidden = S.vistaU !== "g";
  document.querySelectorAll("#uVista button").forEach(b => b.classList.toggle("on", b.dataset.vista === S.vistaU));
  if (S.vistaU === "g") {
    // galeria: todos os veículos do filtro (inclusive sem viagem no período), na ordem da tabela
    const naTabela = linhas.map(l => l.veic);
    const resto = V.map((v, vi) => vi).filter(vi => veicOk(vi) && ccOk(V[vi].cc_atual) && !naTabela.includes(vi)
      && (!b || (V[vi].placa + " " + V[vi].modelo + " " + ccNome(V[vi].cc_atual) + " " + V[vi].tipo).toLowerCase().includes(b)));
    galeria("uGal", naTabela.concat(resto));
  }
  xlsAtual = {nome: "utilizacao_por_veiculo", aba: "Utilização", titulo: "Utilização por veículo",
    cols: [{t: "Placa", k: "placa", w: 10}, {t: "Modelo", k: "modelo", w: 22}, {t: "Tipo", k: "tipo", w: 10}, {t: "Centro de custo atual", k: "cc", w: 18},
           {t: "Viagens", k: "viagens", w: 9, f: "int"}, {t: "Km", k: "km", w: 11, f: "int"}, {t: "Horas ligado", k: "hu", w: 11, f: "dec"},
           {t: "% ocioso", k: "ocioso", w: 9, f: "pct"}, {t: "Km/L", k: "kml", w: 8, f: "dec"}, {t: "Dias com uso", k: "ndias", w: 10, f: "int"},
           {t: "Dias sem uso", k: "semuso", w: 10, f: "int"}, {t: "Vel. máx. (km/h)", k: "vmax", w: 10, f: "int"}],
    linhas};
}

/* ================================== ALERTAS ================================= */
function abaA() {
  const a = AL.filter(linhaOk);
  const ar = S.regra ? a.filter(r => r.regra === IR[S.regra]) : a;
  const regras = ORDEM_REGRA.filter(r => r in IR);
  const porDia = r => { const v = Array(S.ate - S.de + 1).fill(0); a.filter(x => x.regra === IR[r]).forEach(x => v[x.dia - S.de] += x.qtd); return v; };
  const semanal = v => { const o = []; for (let i = 0; i < v.length; i += 7) o.push(sum(v.slice(i, i + 7))); return o; };
  const vel = a.filter(x => x.vel_maxima != null);
  const vmax = vel.length ? Math.max(...vel.map(x => x.vel_maxima)) : null;
  const qtdR = r => sum(a.filter(x => x.regra === IR[r]), x => x.qtd);
  const veicAlerta = new Set(ar.map(x => x.veic)).size;
  const ocioso = sum(a.filter(x => x.regra === IR["Motor ocioso"]), x => x.ocioso_min || 0);
  $("aK").innerHTML = [
    {l: "Veículos com alerta", v: nf(veicAlerta), s: S.regra ? "com " + S.regra.toLowerCase() : "clique num alerta para filtrar", c: "var(--tv)", sr: semanal(porDia(regras[0]).map((_, i) => regras.reduce((s, r) => s + porDia(r)[i], 0))), k: null},
    ...regras.map(r => ({l: r, v: r === "Motor ocioso" ? nf(ocioso / 60) + "<small>h</small>" : nf(qtdR(r)), s: r === "Excesso de velocidade" ? `máxima ${nf(vmax)} km/h` : r === "Motor ocioso" ? `${nf(qtdR(r))} paradas de ${"≥"}5 min` : "no período", c: COR_REGRA[r], sr: semanal(porDia(r)), k: r})),
  ].map(k => `<button type="button" class="ac ${S.regra && k.k === S.regra ? "on" : S.regra && k.k ? "dim" : ""}" data-k="${k.k || ""}" style="--c:${k.c}"><span class="l">${k.l}</span><span class="v">${k.v}</span><span class="s">${k.s}</span>${spark(k.sr, k.c, "")}</button>`).join("");
  $("aK").querySelectorAll(".ac").forEach(b => b.onclick = () => { const k = b.dataset.k || null; S.regra = S.regra === k ? null : k; abaA(); });

  // maiores velocidades: velocímetro + top 8 (veículo, dia)
  const ev = AL.filter(x => linhaOk(x) && x.vel_maxima != null).sort((p, q) => q.vel_maxima - p.vel_maxima);
  const vist = new Set(), top = [];
  for (const x of ev) { if (vist.has(x.veic)) continue; vist.add(x.veic); top.push(x); if (top.length === 8) break; }
  $("aVelAs").textContent = `${nf(qtdR("Excesso de velocidade"))} excessos`;
  $("aVel").innerHTML = gauge(vmax) + top.map(x => `<div class="vrow"><b class="pl clk" data-v="${x.veic}"><span class="pt">${esc(V[x.veic].placa)}</span></b><span>${esc(ccNome(x.cc))} · ${DSEM[dow(DIAS[x.dia])]} ${fmtD(DIAS[x.dia])} ${String(x.hora).padStart(2, "0")}h</span><em>${nf(x.vel_maxima)}</em></div>`).join("");

  // mapa de calor dia da semana x hora
  const m = Array.from({length: 7}, () => Array(24).fill(0));
  ar.forEach(x => m[dow(DIAS[x.dia])][x.hora] += x.qtd);
  let mx = 0, pico = [0, 0]; m.forEach((l, d) => l.forEach((v, h) => { if (v > mx) { mx = v; pico = [d, h]; } }));
  const tot = sum(ar, x => x.qtd);
  $("aHeatSub").innerHTML = mx ? `Pico: <b>${DSEM[pico[0]]} às ${pico[1]}h</b> (${nf(mx)} ocorrências, ${pct(mx / tot)} do total). Passe o mouse para ver cada célula.` : "";
  const W = 760, H = 300, L = 34, T = 18, cw = (W - L) / 24, ch = (H - T) / 7, ordem = [1, 2, 3, 4, 5, 6, 0];
  let g = "";
  for (let h = 0; h < 24; h += 3) g += `<text class="ax" x="${L + h * cw + cw / 2}" y="12" text-anchor="middle">${String(h).padStart(2, "0")}h</text>`;
  ordem.forEach((d, row) => {
    g += `<text class="ax" x="${L - 6}" y="${T + row * ch + ch / 2 + 4}" text-anchor="end">${DSEM[d]}</text>`;
    for (let h = 0; h < 24; h++) {
      const v = m[d][h], o = mx ? Math.sqrt(v / mx) : 0;
      g += `<rect class="hcell" x="${L + h * cw}" y="${T + row * ch}" width="${cw}" height="${ch}" rx="3" style="fill:color-mix(in srgb,${S.regra ? COR_REGRA[S.regra] : "var(--t0)"} ${Math.round(6 + 94 * o)}%,var(--card))" data-tip="<b>${DSEM[d]} ${h}h–${h + 1}h</b>${nf(v)} ocorrências"/>`;
    }
  });
  $("aHeat").innerHTML = `<svg class="ch" viewBox="0 0 ${W} ${H}">${g}</svg><div class="heat-lg">menos <i></i> mais (escala de raiz quadrada)</div>`;

  // ocorrências por dia empilhadas
  legenda("aLg", regras, S.regra, n => { S.regra = S.regra === n ? null : n; abaA(); });
  const lab = []; for (let i = S.de; i <= S.ate; i++) lab.push(fmtD(DIAS[i]));
  barras("aDia", lab, (S.regra ? [S.regra] : regras).map(r => ({nome: r, cor: COR_REGRA[r], vals: porDia(r)})),
    {tipLabel: i => DSEM[dow(DIAS[S.de + i])] + " " + fmtDA(DIAS[S.de + i])});

  // pontos de atenção (view gold.vw_pontos_atencao)
  const pp = PTS.filter(p => !S.regra || p.regra === S.regra || !["Excesso de velocidade", "Motor ocioso"].includes(S.regra));
  const sel = ["Excesso de velocidade", "Motor ocioso"].flatMap(r => pp.filter(p => p.regra === r).slice(0, 4));
  $("aPts").innerHTML = sel.map(p => `<div class="apt" style="--c:${COR_REGRA[p.regra]}"><div class="h"><b class="pt-c">${esc(p.trecho.split(", ").slice(0, 2).join(", "))}</b><em>${nf(p.ocorrencias)}</em></div><p>${esc(p.regra)} · ${esc(p.cidade)}</p><p class="m">${p.veiculos} veículos · ${p.regra === "Motor ocioso" ? nf(p.ocioso_min / 60, 1) + " h paradas com motor ligado" : "máxima " + nf(p.vel_maxima) + " km/h"} · último ${fmtD(p.ultima)}</p></div>`).join("");

  // ranking de veículos empilhado por regra
  const rv = {}; ar.forEach(x => { const r = rv[x.veic] ||= {t: 0, p: {}}; r.t += x.qtd; r.p[x.regra] = (r.p[x.regra] || 0) + x.qtd; });
  const rk = Object.entries(rv).sort((p, q) => q[1].t - p[1].t).slice(0, 20), mr = rk.length ? rk[0][1].t : 1;
  $("aRank").innerHTML = rk.length ? rk.map(([vi, r]) => `<div class="rkr" data-tip="<b>${esc(V[vi].placa)}</b>${esc(V[vi].modelo)} · ${esc(ccNome(V[vi].cc_atual))}<br>${regras.filter(n => r.p[IR[n]]).map(n => `${n}: ${nf(r.p[IR[n]])}`).join("<br>")}"><span class="p pl clk" data-v="${vi}"><span class="pt">${esc(V[vi].placa)}</span></span><div class="sb">${regras.filter(n => r.p[IR[n]]).map(n => `<i style="--c:${COR_REGRA[n]};width:${100 * r.p[IR[n]] / mr}%"></i>`).join("")}</div><span class="n">${nf(r.t)}</span></div>`).join("") : `<div class="empty">Sem alertas no filtro.</div>`;

  // mapa: alertas a cada 100 km por cidade (centro de custo) e por região
  const kmcc = {}; USO.filter(linhaOk).forEach(r => kmcc[r.cc] = (kmcc[r.cc] || 0) + r.km);
  const acc = {}; ar.forEach(x => acc[x.cc] = (acc[x.cc] || 0) + x.qtd);
  const regA = {};
  Object.keys(kmcc).filter(ci => +ci >= 0).forEach(ci => { const r = regA[CC[ci].regional] ||= {n: 0, km: 0}; r.n += acc[ci] || 0; r.km += kmcc[ci]; });
  Object.values(regA).forEach(r => { r.v = r.km ? 100 * r.n / r.km : 0; r.lab = nf(r.v, 1); });
  mapaBrasil("aCC", Object.keys(kmcc).filter(ci => +ci >= 0 && kmcc[ci] > 0).map(ci => {
    const t = 100 * (acc[ci] || 0) / kmcc[ci];
    return {cidade: CC[ci].cidade, v: t, lab: nf(t, 1), tip: `<b>${esc(CC[ci].cidade)}</b>${esc(CC[ci].centro_custo)} · ${CC[ci].regional}<br>${nf(t, 1)} alertas a cada 100 km<br>${nf(acc[ci] || 0)} alertas · ${nf(kmcc[ci])} km`};
  }), regA, S.regra ? COR_REGRA[S.regra] : "var(--t0)", "alertas a cada 100 km", true);

  const cv = {}; ar.forEach(x => { const k = x.veic + "|" + x.regra; const r = cv[k] ||= {veic: x.veic, regra: x.regra, n: 0, vmax: null, oc: 0}; r.n += x.qtd; if (x.vel_maxima != null) r.vmax = Math.max(r.vmax || 0, x.vel_maxima); r.oc += x.ocioso_min || 0; });
  xlsAtual = {nome: "alertas_por_veiculo", aba: "Alertas", titulo: "Alertas por veículo e tipo",
    cols: [{t: "Placa", k: "placa", w: 10}, {t: "Modelo", k: "modelo", w: 22}, {t: "Centro de custo atual", k: "cc", w: 18}, {t: "Alerta", k: "alerta", w: 20},
           {t: "Ocorrências", k: "n", w: 11, f: "int"}, {t: "Velocidade máxima (km/h)", k: "vmax", w: 13, f: "int"}, {t: "Minutos de motor ocioso", k: "oc", w: 13, f: "int"}],
    linhas: Object.values(cv).sort((p, q) => q.n - p.n).map(r => ({placa: V[r.veic].placa, modelo: V[r.veic].modelo, cc: ccNome(V[r.veic].cc_atual),
      alerta: D.regras[r.regra], n: r.n, vmax: r.vmax, oc: r.oc ? Math.round(r.oc) : null}))};
}
function gauge(v) {
  const mn = 60, mx = 180, a = x => Math.PI * (1 - (Math.max(mn, Math.min(mx, x)) - mn) / (mx - mn)), cx = 150, cy = 130, r = 100;
  const pt = (x, rr) => [cx + rr * Math.cos(a(x)), cy - rr * Math.sin(a(x))];
  const arco = (x1, x2, c) => { const [p1, q1] = pt(x1, r), [p2, q2] = pt(x2, r); return `<path d="M${p1} ${q1} A${r} ${r} 0 0 1 ${p2} ${q2}" fill="none" stroke="${c}" stroke-width="22"/>`; };
  const [nx, ny] = pt(v ?? mn, r - 6);
  return `<svg class="gauge" viewBox="0 0 300 170">${arco(60, 90, "var(--line)")}${arco(90, 110, "var(--t0)")}${arco(110, 150, "var(--t3)")}${arco(150, 180, "var(--tred)")}
  ${[60, 90, 110, 150, 180].map(x => { const [tx, ty] = pt(x, r + 22); return `<text class="ax" x="${tx}" y="${ty + 4}" text-anchor="middle">${x}</text>`; }).join("")}
  <line x1="${pt(v ?? mn, r - 30)[0]}" y1="${pt(v ?? mn, r - 30)[1]}" x2="${nx}" y2="${ny}" stroke="var(--ink)" stroke-width="5" stroke-linecap="round"/>
  <text x="150" y="128" text-anchor="middle" font-size="44" font-weight="800" fill="var(--tred)">${v == null ? "–" : nf(v)}</text><text class="ax" x="150" y="150" text-anchor="middle">km/h · máxima no filtro</text></svg>`;
}

/* =================================== CUSTOS ================================= */
function abaC() {
  const os = OS.filter(o => veicOk(o.veic) && ccOk(o.cc) && dataOk(o.data_os));
  // custo da OS = serviço (negociado) + peças + locação do substituto
  const serv = o => o.negociado || 0, pec = o => o.pecas || 0, loc = o => o.custo_locacao || 0, tot = o => o.custo_total || 0;
  const total = sum(os, tot), orcN = sum(os.filter(o => o.negociado != null), o => o.orcado || 0), negN = sum(os, serv);
  const u = USO.filter(linhaOk), km = sum(u, r => r.km);
  const porT = t => sum(os.filter(o => o.tipo_manutencao === t), tot);
  const comSub = os.filter(o => o.substituto);
  const veicsOS = new Set(os.map(o => o.veic)).size;
  kpis("cK", [
    ["Custo de manutenção", brl(total), `${os.length} OS · serviço + peças + locação`],
    ["Serviço da oficina", brl(negN), `${pct(total ? negN / total : 0)} do custo`],
    ["Peças", brl(sum(os, pec)), `${pct(total ? sum(os, pec) / total : 0)} do custo`],
    ["Locação de substitutos", brl(sum(os, loc)), `${comSub.length} OS com veículo substituto`],
    ["Economia na negociação", pct(orcN ? (orcN - negN) / orcN : 0), `${brl(orcN - negN)} abaixo do 1º orçamento`],
    ["Custo por km", "R$ " + nf(km ? total / km : 0, 2), `${nf(km)} km rodados no período`],
    ["Custo por veículo atendido", brl(veicsOS ? total / veicsOS : 0), `${veicsOS} veículos com OS`],
    ["Corretiva", pct(total ? porT("Corretiva") / total : 0), `${brl(porT("Corretiva"))} · preventiva ${pct(total ? porT("Preventiva") / total : 0)}`],
  ]);
  const comp = [["Serviço", "var(--own)", serv], ["Peças", "var(--t3)", pec], ["Locação de substitutos", "var(--tred)", loc]];
  const corC = Object.fromEntries(comp.map(c => [c[0], c[1]]));
  legenda("cLg", comp.map(c => c[0]), null, null, corC);
  const ms = meses();
  barras("cMes", ms.map(nomeMes), comp.map(([nome, cor, f]) => ({nome, cor, vals: ms.map(m => Math.round(sum(os.filter(o => o.data_os.startsWith(m)), f)))})), {h: 220, passo: 1, fmt: brlCheio});

  const pc = {}; os.forEach(o => { const g = pc[o.cc] ||= {t: 0, s: 0, n: 0}; g.t += tot(o); g.s += serv(o) + pec(o); g.n++; });
  mbar("cCC", Object.entries(pc).sort((a, b) => b[1].t - a[1].t).map(([ci, g]) => ({k: ccNome(+ci), v: g.t, lab: brl(g.t), sub: `${g.n} OS`,
    tip: `<b>${esc(ccNome(+ci))}</b>conserto (serviço + peças) ${brlCheio(g.s)}<br>locação ${brlCheio(g.t - g.s)}`})));

  const kt = {}, ct = {};
  u.forEach(r => kt[V[r.veic].tipo] = (kt[V[r.veic].tipo] || 0) + r.km);
  os.forEach(o => ct[V[o.veic].tipo] = (ct[V[o.veic].tipo] || 0) + tot(o));
  mbar("cTp", Object.keys(kt).filter(t => kt[t] > 0).map(t => ({t, v: (ct[t] || 0) / kt[t]})).sort((a, b) => b.v - a.v)
    .map(x => ({k: x.t, v: x.v, lab: "R$ " + nf(x.v, 2), sub: `${brl(ct[x.t] || 0)} ÷ ${curto(kt[x.t])} km`, cls: "s", c: "var(--own)"})));

  // veículo parado com substituto
  const par = comSub.slice().sort((a, b) => b.custo_total - a.custo_total);
  $("cParAs").textContent = `${par.length} OS · locação ${brl(sum(par, loc))} · total ${brl(sum(par, tot))}`;
  tabela("cPar", [
    {k: "numero_os", t: "OS", f: o => `<span class="sm">${o.numero_os}</span>`}, {k: "placa", t: "Placa", f: o => placaCel(o.veic)},
    {k: "sis", t: "Sistema", f: o => `${esc(o.tipo_sistema)}<div class="sm">${esc(o.etapa)}</div>`},
    {k: "sub", t: "Substituto", f: o => `<span class="mono">${esc(o.placa_substituto || "sem placa")}</span>`},
    {k: "al", t: "Aluguel", f: o => `${esc(o.tipo_aluguel || "–")}<div class="sm">${brlCheio(o.valor_aluguel)}${o.tipo_aluguel === "Diária" ? "/dia" : ""}</div>`},
    {k: "dias_locacao", t: "Dias", n: 1, f: o => o.dias_locacao ?? "–"},
    {k: "c1", t: "Conserto", n: 1, f: o => brlCheio(serv(o) + pec(o))}, {k: "c2", t: "Locação", n: 1, f: o => brlCheio(loc(o))},
    {k: "c3", t: "Custo total parado", n: 1, f: o => `<b>${brlCheio(tot(o))}</b>`},
  ], par.slice(0, 12));

  const pv = {}; os.forEach(o => { const g = pv[o.veic] ||= {veic: o.veic, t: 0, n: 0, cor: 0, loc: 0}; g.t += tot(o); g.loc += loc(o); g.n++; if (o.tipo_manutencao === "Corretiva") g.cor++; });
  const kv = {}; u.forEach(r => kv[r.veic] = (kv[r.veic] || 0) + r.km);
  const linhas = Object.values(pv).sort((a, b) => b.t - a.t);
  tabela("cTab", [
    {k: "placa", t: "Placa", f: g => placaCel(g.veic)}, {k: "tipo", t: "Tipo", f: g => V[g.veic].tipo}, {k: "cc", t: "Centro de custo atual", f: g => esc(ccNome(V[g.veic].cc_atual))},
    {k: "n", t: "OS", n: 1}, {k: "cor", t: "Corretivas", n: 1}, {k: "t", t: "Custo total", n: 1, f: g => brlCheio(g.t)},
    {k: "loc", t: "Dele, locação", n: 1, f: g => g.loc ? brlCheio(g.loc) : "–"},
    {k: "km", t: "Km no período", n: 1, f: g => nf(kv[g.veic] || 0)}, {k: "ckm", t: "R$/km", n: 1, f: g => kv[g.veic] ? nf(g.t / kv[g.veic], 2) : "–"},
    {k: "fipe", t: "% da FIPE", n: 1, f: g => V[g.veic].fipe ? pct(g.t / V[g.veic].fipe) : "–"},
  ], linhas.slice(0, 15));
  xlsAtual = {nome: "custo_por_veiculo", aba: "Custos", titulo: "Custo de manutenção por veículo (serviço + peças + locação)",
    cols: [{t: "Placa", k: "placa", w: 10}, {t: "Modelo", k: "modelo", w: 22}, {t: "Tipo", k: "tipo", w: 10}, {t: "Centro de custo atual", k: "cc", w: 18},
           {t: "OS", k: "n", w: 6, f: "int"}, {t: "Corretivas", k: "cor", w: 10, f: "int"}, {t: "Custo total", k: "t", w: 14, f: "brl"},
           {t: "Dele, locação", k: "loc", w: 13, f: "brl"}, {t: "Km no período", k: "km", w: 12, f: "int"}, {t: "R$/km", k: "ckm", w: 9, f: "brl"},
           {t: "Valor FIPE", k: "fipe", w: 14, f: "brl"}],
    linhas: linhas.map(g => ({placa: V[g.veic].placa, modelo: V[g.veic].modelo, tipo: V[g.veic].tipo, cc: ccNome(V[g.veic].cc_atual), n: g.n, cor: g.cor,
      t: +g.t.toFixed(2), loc: +g.loc.toFixed(2), km: Math.round(kv[g.veic] || 0), ckm: kv[g.veic] ? +(g.t / kv[g.veic]).toFixed(2) : null, fipe: V[g.veic].fipe}))};
}

/* ============================ controles e textos ============================ */
const TEXTO = {
  M: ["Manutenção da Frota", `Posição em <b>${fmtDA(REF)}</b>: onde cada OS está no processo, quanto tempo cada etapa leva contra a meta, o que atacar primeiro e o que a negociação economizou.`],
  U: ["Utilização da Frota — Viagens", "Viagens confiáveis da telemetria (outliers retirados na silver e revisados à mão). O centro de custo é o vigente no dia da viagem."],
  A: ["Alertas de Telemetria", "Excesso de velocidade, freada, aceleração e curva bruscas e motor ligado parado (≥ 5 min). Clique num card para filtrar o tipo de alerta."],
  C: ["Custos de Manutenção", "Custo de cada OS = serviço negociado com a oficina + peças + aluguel do veículo substituto, cruzado com os km rodados da telemetria. Sem receita: o projeto não simula faturamento."],
};
const RODAPE = {
  M: ["Abertas = sem data de saída da oficina. Atrasada = aberta e com previsão de saída anterior à data de referência.", "SLA, custos e reincidências usam as OS abertas no período; a fila e os cards de posição ignoram o período."],
  U: ["Horas ligado = duração das viagens; ocioso = tempo de motor ligado com o veículo parado.", "Veículos sem rastreador não aparecem nesta aba.", "Mapa: contorno dos estados de @svg-maps/brazil (CC BY 4.0). Cidades reais; veículos, placas, motoristas e oficinas são fictícios."],
  A: ["Motor ocioso conta só paradas de 5 min ou mais (regra do pipeline).", "Velocidade de 150 km/h ou mais só entra quando o odômetro confirma o deslocamento.", "Mapa: contorno dos estados de @svg-maps/brazil (CC BY 4.0). Cidades reais; veículos, placas, motoristas e oficinas são fictícios."],
  C: ["Custo no mês de abertura da OS. Economia = orçado − negociado. Locação = diária × dias parado, ou o valor fixo do período.", "% da FIPE = custo de manutenção no período ÷ valor FIPE do veículo."],
};
function render() {
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === S.tab));
  ["M", "U", "A", "C"].forEach(t => $("view" + t).hidden = t !== S.tab);
  $("heroT").textContent = TEXTO[S.tab][0];
  $("heroP").innerHTML = TEXTO[S.tab][1];
  $("perTxt").textContent = S.tab === "M" ? "posição em " + fmtDA(REF) : fmtD(DIAS[S.de]) + " – " + fmtDA(DIAS[S.ate]);
  $("note").innerHTML = `Dados fictícios gerados pelo projeto · atualizados em ${D.meta.gerado_em} · telemetria de ${fmtDA(D.meta.inicio)} a ${fmtDA(REF)}.`;
  $("foot").innerHTML = RODAPE[S.tab].concat(["Fonte: views da camada gold (banco/07_views.sql), exportadas por pipeline/exportar_dashboard.py. Código: github.com/BrunoLima-085/brn-frota-data-platform"]).map(t => `<li>${t}</li>`).join("");
  const f = [S.reg, S.cc && ccNome(+S.cc), S.tp].filter(Boolean);
  $("fResumo").textContent = (f.length ? f.join(" · ") + " · " : "") + fmtD(DIAS[S.de]) + "–" + fmtD(DIAS[S.ate]);
  ({M: abaM, U: abaU, A: abaA, C: abaC})[S.tab]();
}
function opcoes(sel, lista, todos = "Todos") { $(sel).innerHTML = `<option value="">${todos}</option>` + lista.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join(""); }
function opcoesCC() {
  opcoes("fCC", CC.map((c, i) => [i, c.centro_custo]).filter(([i]) => !S.reg || CC[i].regional === S.reg));
  $("fCC").value = S.cc;
}
function padrao() {
  S.ate = DIAS.length - 1; S.de = Math.max(0, S.ate - 89); S.reg = S.cc = S.tp = ""; S.regra = null; S.etapa = "abertas";
  $("fDe").value = DIAS[S.de]; $("fAte").value = DIAS[S.ate]; $("fReg").value = ""; $("fTp").value = ""; opcoesCC();
}
function resumoFiltros() {
  return [fmtDA(DIAS[S.de]) + " a " + fmtDA(DIAS[S.ate]), S.reg && "regional " + S.reg, S.cc && ccNome(+S.cc), S.tp && "tipo " + S.tp, S.regra && "alerta " + S.regra]
    .filter(Boolean).join(" · ");
}
function exportarAba() {
  if (xlsAtual) exportarExcel(xlsAtual.nome, xlsAtual.aba, xlsAtual.cols, xlsAtual.linhas, xlsAtual.titulo);
}
function iniciar() {
  if (!D) { document.querySelector(".wrap").insertAdjacentHTML("beforeend", `<div class="sec">Arquivo dados.js não encontrado. Rode <b>py rodar_pipeline.py --etapas dashboard</b>.</div>`); return; }
  try { const t = localStorage.getItem("brnTema"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* sem storage */ }
  $("themeBtn").onclick = () => {
    const escuro = document.documentElement.dataset.theme ? document.documentElement.dataset.theme !== "dark" : !matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = escuro ? "dark" : "light";
    try { localStorage.setItem("brnTema", document.documentElement.dataset.theme); } catch (e) { /* sem storage */ }
  };
  opcoes("fReg", [...new Set(CC.map(c => c.regional))].sort().map(r => [r, r]), "Todas");
  opcoes("fTp", [...new Set(V.map(v => v.tipo))].sort().map(t => [t, t]));
  [$("fDe"), $("fAte")].forEach(i => { i.min = DIAS[0]; i.max = DIAS[DIAS.length - 1]; });
  padrao();
  const tabInicial = (location.hash || "").replace("#", "").toUpperCase();
  if ("MUAC".includes(tabInicial) && tabInicial) S.tab = tabInicial;
  document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => { S.tab = b.dataset.tab; history.replaceState(null, "", "#" + S.tab.toLowerCase()); render(); });
  $("fDe").onchange = () => { const i = IDX[$("fDe").value]; if (i != null) S.de = Math.min(i, S.ate); $("fDe").value = DIAS[S.de]; render(); };
  $("fAte").onchange = () => { const i = IDX[$("fAte").value]; if (i != null) S.ate = Math.max(i, S.de); $("fAte").value = DIAS[S.ate]; render(); };
  $("fReg").onchange = () => { S.reg = $("fReg").value; S.cc = ""; opcoesCC(); render(); };
  $("fCC").onchange = () => { S.cc = $("fCC").value; render(); };
  $("fTp").onchange = () => { S.tp = $("fTp").value; render(); };
  $("btnReset").onclick = () => { padrao(); render(); };
  $("btnXls").onclick = exportarAba;
  // painel do veículo: qualquer elemento com data-v (placa, galeria, listas) abre
  document.addEventListener("click", e => { const el = e.target.closest("[data-v]"); if (el) abrirVeiculo(+el.dataset.v); });
  $("d-close").onclick = fecharVeiculo; $("scrim").onclick = fecharVeiculo;
  // Frota
  $("frotaBtn").onclick = abrirFrota; $("fmClose").onclick = fecharFrota;
  $("fmScrim").onclick = e => { if (e.target.id === "fmScrim") fecharFrota(); };
  $("fmQ").oninput = () => { FS.q = $("fmQ").value; desenharFrota(); };
  [["fmGr", "tp"], ["fmFil", "fil"], ["fmCC", "cc"], ["fmCt", "ras"]].forEach(([id, k]) => $(id).onchange = () => { FS[k] = $(id).value; desenharFrota(); });
  $("fmReset").onclick = abrirFrota;
  $("fmXls").onclick = () => exportarExcel("frota_completa", "Frota", FROTA_COLS, frotaFiltrada(), "Frota completa");
  // Guia
  $("guiaBtn").onclick = abrirGuia; $("gdClose").onclick = fecharGuia;
  $("gdScrim").onclick = e => { if (e.target.id === "gdScrim") fecharGuia(); };
  $("gdPdf").onclick = () => { document.body.classList.add("print-guia"); window.print(); setTimeout(() => document.body.classList.remove("print-guia"), 500); };
  document.querySelectorAll(".gd-per").forEach(el => el.textContent = fmtDA(D.meta.inicio) + " a " + fmtDA(REF));
  document.addEventListener("keydown", e => { if (e.key === "Escape") { fecharVeiculo(); fecharFrota(); fecharGuia(); } });
  // Utilização: tabela ou galeria
  document.querySelectorAll("#uVista button").forEach(b => b.onclick = () => { S.vistaU = b.dataset.vista; abaU(); });
  $("uBusca").oninput = () => { S.buscaU = $("uBusca").value; abaU(); };
  $("fTog").onclick = () => $("filtros").classList.toggle("fcol");
  if (matchMedia("(max-width:760px)").matches) $("filtros").classList.add("fcol");
  render();
}
iniciar();
