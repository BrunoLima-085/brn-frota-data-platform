/* =====================================================================
   Painel do veículo, tabela da Frota, galeria e exportação para Excel
   ---------------------------------------------------------------------
   Usa os dados e os auxiliares do app.js (V, USO, AL, OS, esc, nf...).
   Este arquivo só define funções: quem chama é o app.js.
   ===================================================================== */
"use strict";

/* ------------------------------ Excel (.xlsx) ------------------------------ */
// colunas: [{t: título, k: chave, w: largura, f: "brl" | "int" | "dec" | "pct" | "data"}]
async function exportarExcel(nome, aba, colunas, linhas, titulo) {
  if (!window.ExcelJS) { alert("Biblioteca do Excel não carregou (js/vendor/exceljs.min.js)."); return; }
  const wb = new ExcelJS.Workbook();
  wb.creator = "brn-frota-data-platform";
  const ws = wb.addWorksheet(aba.slice(0, 31), {views: [{state: "frozen", ySplit: 3}]});
  ws.mergeCells(1, 1, 1, colunas.length);
  ws.getCell(1, 1).value = titulo;
  ws.getCell(1, 1).font = {bold: true, size: 13, color: {argb: "FF172527"}};
  ws.getCell(2, 1).value = `Dados fictícios · gerado em ${D.meta.gerado_em} · filtros: ${resumoFiltros()}`;
  ws.getCell(2, 1).font = {italic: true, size: 9, color: {argb: "FF6B7280"}};
  const cab = ws.getRow(3);
  colunas.forEach((c, i) => {
    const cel = cab.getCell(i + 1);
    cel.value = c.t;
    cel.font = {bold: true, color: {argb: "FFFFFFFF"}};
    cel.fill = {type: "pattern", pattern: "solid", fgColor: {argb: "FF172527"}};
    cel.alignment = {vertical: "middle", wrapText: true};
    cel.border = {bottom: {style: "medium", color: {argb: "FFED8948"}}};
    ws.getColumn(i + 1).width = c.w || 14;
  });
  cab.height = 30;
  const FMT = {brl: '"R$" #,##0.00', int: "#,##0", dec: "#,##0.0", pct: "0.0%", data: "dd/mm/yyyy"};
  linhas.forEach(l => {
    const row = ws.addRow(colunas.map(c => {
      const v = l[c.k];
      if (c.f === "data" && v) return new Date(v + "T12:00:00");
      return v ?? null;
    }));
    colunas.forEach((c, i) => { if (FMT[c.f]) row.getCell(i + 1).numFmt = FMT[c.f]; });
  });
  ws.autoFilter = {from: {row: 3, column: 1}, to: {row: 3, column: colunas.length}};
  const buf = await wb.xlsx.writeBuffer();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([buf], {type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}));
  a.download = `${nome}_${DIAS[S.de]}_a_${DIAS[S.ate]}.xlsx`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1500);
}

/* ------------------------------ placa e textos ------------------------------ */
// placa Mercosul em HTML/CSS (faixa azul "BRASIL" + caracteres)
const placaMercosul = (placa, grande = false) =>
  `<span class="mplaca${grande ? " g" : ""}"><span class="mf">BRASIL</span><span class="mc">${esc(placa)}</span></span>`;
const anoRef = () => +REF.slice(0, 4);
const idadeVeic = v => v.ano ? anoRef() - v.ano : null;
const corEtapaOS = e => COR_ETAPA[e] || "var(--ink3)";
const placaBtn = (vi, comModelo = true) =>
  `<span class="pl clk" data-v="${vi}"><span class="pt">${esc(V[vi].placa)}</span></span>${comModelo ? `<div class="sm">${esc(V[vi].modelo)}</div>` : ""}`;

/* ------------------------------ painel do veículo ------------------------------ */
function abrirVeiculo(vi) {
  const v = V[vi];
  const uso = USO.filter(r => r.veic === vi && diaOk(r.dia));
  const al = AL.filter(r => r.veic === vi && diaOk(r.dia));
  const os = OS.filter(o => o.veic === vi).sort((a, b) => b.data_os.localeCompare(a.data_os));
  const km = sum(uso, r => r.km), hu = sum(uso, r => r.horas_uso), ho = sum(uso, r => r.horas_ocioso);
  const diasUso = new Set(uso.map(r => r.dia)).size, vg = sum(uso, r => r.viagens);
  const qtd = nome => sum(al.filter(r => r.regra === IR[nome]), r => r.qtd);
  const vmax = Math.max(0, ...al.filter(r => r.vel_maxima != null).map(r => r.vel_maxima));
  const bruscos = qtd("Freada brusca") + qtd("Aceleração brusca") + qtd("Curva brusca");
  const aberta = os.find(o => !o.saida);
  const custoOS = sum(os, o => o.custo_total || 0);
  const idade = idadeVeic(v);
  const per = fmtD(DIAS[S.de]) + " a " + fmtDA(DIAS[S.ate]);

  $("d-eye").textContent = `${v.tipo} · ${v.filial || "—"}`;
  $("d-title").textContent = v.placa;
  $("d-badges").innerHTML = (idade != null ? `<span class="badge ${idade >= 8 ? "wr inv" : ""}" style="background:var(--orange);color:#fff">${idade} ${idade === 1 ? "ANO" : "ANOS"}</span> ` : "") +
    (aberta ? `<span class="badge" style="background:${corEtapaOS(aberta.etapa)};color:#fff">${esc(aberta.etapa.toUpperCase())}</span> ` : "") +
    (!v.rastreador ? `<span class="badge wr inv">SEM RASTREADOR</span>` : "");

  // km por dia (mini barras)
  const kmDia = []; for (let i = S.de; i <= S.ate; i++) kmDia.push(0);
  uso.forEach(r => kmDia[r.dia - S.de] += r.km);
  const mxKm = Math.max(...kmDia, 1), bw = 600 / kmDia.length;
  const mini = `<svg class="ch" viewBox="0 0 600 90" preserveAspectRatio="none">${kmDia.map((k, i) =>
    `<rect x="${(i * bw + bw * .1).toFixed(1)}" y="${(84 - 80 * k / mxKm).toFixed(1)}" width="${(bw * .8).toFixed(1)}" height="${(80 * k / mxKm).toFixed(1)}" style="fill:var(--own)"/>` +
    `<rect class="hit" x="${(i * bw).toFixed(1)}" y="0" width="${bw.toFixed(1)}" height="90" data-tip="<b>${DSEM[dow(DIAS[S.de + i])]} ${fmtDA(DIAS[S.de + i])}</b>${nf(k)} km"/>`).join("")}</svg>`;

  $("d-body").innerHTML = `
  <div class="ficha">
    ${placaMercosul(v.placa, true)}
    <div class="fd"><b>${esc(v.marca)} ${esc(v.modelo)}</b><span>${esc(v.tipo)} · ${esc(v.cor || "—")} · ${v.ano ?? "—"}/${v.ano_modelo ?? "—"}</span>
      <span>${esc(ccNome(v.cc_atual))} · ${esc(v.contrato || "sem contrato")}</span></div>
  </div>
  <div class="dkpis d4">
    <div class="dk"><div class="l">Valor FIPE</div><div class="v">${brl(v.fipe)}</div><div class="s">${idade != null ? idade + (idade === 1 ? " ano" : " anos") + " de uso" : "—"}</div></div>
    <div class="dk"><div class="l">Manutenção acumulada</div><div class="v">${brl(custoOS)}</div><div class="s">${v.fipe ? pct(custoOS / v.fipe) + " da FIPE" : "—"} · ${os.length} OS</div></div>
    <div class="dk"><div class="l">Situação hoje</div><div class="v" style="font-size:16px">${aberta ? esc(aberta.etapa) : "Operando"}</div><div class="s">${aberta ? `${esc(aberta.tipo_sistema)} · ${esc(aberta.oficina)}` : "sem OS aberta"}</div></div>
    <div class="dk"><div class="l">Última manutenção</div><div class="v">${v.dias_desde_ultima != null ? "há " + nf(v.dias_desde_ultima) + " d" : "—"}</div><div class="s">${v.ultima_data ? fmtDA(v.ultima_data) + " · " + esc(v.ultima_tipo) : "nenhuma concluída"}</div></div>
  </div>
  <div class="ttl">Cadastro</div>
  <dl class="kv">
    <dt>Marca / modelo</dt><dd>${esc(v.marca)} ${esc(v.modelo)}</dd>
    <dt>Ano fab./modelo</dt><dd>${v.ano ?? "—"} / ${v.ano_modelo ?? "—"}</dd>
    <dt>Cor</dt><dd>${esc(v.cor || "—")}</dd>
    <dt>Chassi</dt><dd class="mono">${esc(v.chassi || "—")}</dd>
    <dt>Filial</dt><dd>${esc(v.filial || "—")}</dd>
    <dt>Centro de custo</dt><dd>${esc(ccNome(v.cc_atual))}${v.cc_atual >= 0 ? ` · ${esc(CC[v.cc_atual].regional)}` : ""}</dd>
    <dt>Contrato / operação</dt><dd>${esc(v.contrato || "—")} · ${esc(v.operacao || "—")}</dd>
    <dt>Tipo</dt><dd>${esc(v.tipo)}</dd>
    <dt>Valor FIPE</dt><dd>${brlCheio(v.fipe)}</dd>
    <dt>Rastreador</dt><dd>${v.rastreador ? "Sim" : "Não"}</dd>
    <dt>Blindagem</dt><dd>${v.blindagem ? "Sim" : "Não"}</dd>
    <dt>Status</dt><dd>${esc(v.status || "—")}</dd>
    <dt>Última manutenção</dt><dd>${v.ultima_data ? `${fmtDA(v.ultima_data)} · ${esc(v.ultima_tipo)} (${esc(v.ultima_sistema)}) · há ${nf(v.dias_desde_ultima)} dias` : "nenhuma concluída"}</dd>
  </dl>
  <div><div class="ttl">Utilização · ${per}</div><div class="dkpis">
    <div class="dk"><div class="l">Viagens</div><div class="v">${nf(vg)}</div><div class="s">${nf(diasUso)} dia(s) com uso</div></div>
    <div class="dk"><div class="l">Km rodados</div><div class="v">${nf(km)}</div><div class="s">${diasUso ? nf(km / diasUso, 1) : "–"} km por dia de uso</div></div>
    <div class="dk"><div class="l">Horas de motor ligado</div><div class="v">${nf(hu, 1)} h</div><div class="s">${nf(ho, 1)} h com o veículo parado</div></div>
    <div class="dk"><div class="l">Tempo ligado parado</div><div class="v">${hu ? pct(ho / hu) : "–"}</div><div class="s">do tempo de motor ligado</div></div>
  </div></div>
  ${v.rastreador ? `<div><div class="ttl">Km por dia</div>${uso.length ? mini : '<div class="empty">Sem viagens no período.</div>'}</div>` : ""}
  <div><div class="ttl">Alertas · ${per}</div><div class="dkpis">
    <div class="dk"><div class="l">Excessos de velocidade</div><div class="v">${nf(qtd("Excesso de velocidade"))}</div><div class="s">maior: ${vmax ? nf(vmax) + " km/h" : "—"}</div></div>
    <div class="dk"><div class="l">Condução brusca</div><div class="v">${nf(bruscos)}</div><div class="s">freada, aceleração e curva</div></div>
    <div class="dk"><div class="l">Motor ligado parado</div><div class="v">${nf(qtd("Motor ocioso"))}</div><div class="s">paradas de 5 min ou mais</div></div>
    <div class="dk"><div class="l">Alertas por 100 km</div><div class="v">${km ? nf((bruscos + qtd("Excesso de velocidade")) / km * 100, 1) : "–"}</div><div class="s">velocidade + condução brusca</div></div>
  </div></div>
  <div><div class="ttl">Ordens de serviço · histórico completo (${os.length})</div>
    ${os.length ? `<div class="dkpis" style="margin-bottom:8px">
      <div class="dk"><div class="l">Custo total</div><div class="v">${brl(custoOS)}</div><div class="s">negociado + peças + locação</div></div>
      <div class="dk"><div class="l">Corretivas</div><div class="v">${os.filter(o => o.tipo_manutencao === "Corretiva").length}</div><div class="s">${os.filter(o => o.reincidente).length} reincidência(s)</div></div>
    </div>
    <div class="mtb"><table><thead><tr><th>OS</th><th>Abertura</th><th>Sistema</th><th>Etapa</th><th class="n">Dias parado</th><th class="n">Custo total</th></tr></thead><tbody>
    ${os.map(o => `<tr><td class="mono">${o.numero_os}</td><td>${fmtDA(o.data_os)}</td><td>${esc(o.tipo_sistema)}<div class="sm">${esc(o.tipo_manutencao)} · ${esc(o.oficina)}</div></td>
      <td><span class="pill" style="--c:${corEtapaOS(o.etapa)}">${esc(o.etapa)}</span>${o.substituto ? '<div class="sm">com substituto</div>' : ""}</td>
      <td class="n">${o.dias_parado ?? "–"}</td><td class="n">${brlCheio(o.custo_total)}</td></tr>`).join("")}
    </tbody></table></div>` : '<div class="empty">Nenhuma OS registrada.</div>'}
  </div>`;
  const drawer = $("drawer"), scrim = $("scrim");
  drawer.classList.add("open"); scrim.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
  $("d-body").scrollTop = 0;
}
function fecharVeiculo() {
  $("drawer").classList.remove("open"); $("scrim").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true");
}

/* ------------------------------ tabela da Frota ------------------------------ */
const FROTA_COLS = [
  {t: "Placa", k: "placa", w: 11}, {t: "Marca", k: "marca", w: 12}, {t: "Modelo", k: "modelo", w: 22},
  {t: "Tipo", k: "tipo", w: 10}, {t: "Ano fab.", k: "ano", w: 9, f: "ano"}, {t: "Ano mod.", k: "ano_modelo", w: 9, f: "ano"},
  {t: "Cor", k: "cor", w: 10}, {t: "Chassi", k: "chassi", w: 21}, {t: "Filial", k: "filial", w: 16},
  {t: "Centro de custo", k: "cc_nome", w: 18}, {t: "Regional", k: "regional", w: 13}, {t: "Contrato", k: "contrato", w: 12},
  {t: "Operação", k: "operacao", w: 20}, {t: "Rastreador", k: "rastreador_txt", w: 11}, {t: "Valor FIPE", k: "fipe", w: 13, f: "brl"},
  {t: "Última manutenção", k: "ultima_data", w: 14, f: "data"}, {t: "Dias desde a última", k: "dias_desde_ultima", w: 12, f: "int"},
];
const FS = {q: "", tp: "", fil: "", cc: "", ras: "", sort: ["placa", 1]};
function linhasFrota() {
  return V.map((v, vi) => ({...v, vi, cc_nome: ccNome(v.cc_atual), regional: v.cc_atual >= 0 ? CC[v.cc_atual].regional : "",
    rastreador_txt: v.rastreador ? "Sim" : "Não"}));
}
function abrirFrota() {
  const todos = linhasFrota();
  const op = (id, vals, todosTxt) => { $(id).innerHTML = `<option value="">${todosTxt}</option>` + [...new Set(vals)].filter(Boolean).sort().map(x => `<option>${esc(x)}</option>`).join(""); };
  op("fmGr", todos.map(l => l.tipo), "Todos"); op("fmFil", todos.map(l => l.filial), "Todas");
  op("fmCC", todos.map(l => l.cc_nome), "Todos");
  $("fmCt").innerHTML = `<option value="">Todos</option><option value="Sim">Com rastreador</option><option value="Não">Sem rastreador</option>`;
  ["fmQ", "fmGr", "fmFil", "fmCC", "fmCt"].forEach(id => $(id).value = "");
  Object.assign(FS, {q: "", tp: "", fil: "", cc: "", ras: ""});
  desenharFrota();
  $("fmScrim").classList.add("open"); $("fmScrim").setAttribute("aria-hidden", "false");
}
function frotaFiltrada() {
  const q = FS.q.toLowerCase();
  const [sk, sd] = FS.sort;
  return linhasFrota().filter(l => (!FS.tp || l.tipo === FS.tp) && (!FS.fil || l.filial === FS.fil) && (!FS.cc || l.cc_nome === FS.cc)
      && (!FS.ras || l.rastreador_txt === FS.ras)
      && (!q || [l.placa, l.marca, l.modelo, l.chassi, l.cc_nome, l.contrato].join(" ").toLowerCase().includes(q)))
    .sort((a, b) => (typeof a[sk] === "string" ? (a[sk] || "").localeCompare(b[sk] || "") : (a[sk] ?? -1) - (b[sk] ?? -1)) * sd);
}
function desenharFrota() {
  const ls = frotaFiltrada();
  $("fmSub").textContent = `${V.length} veículos no cadastro · clique na placa para abrir o painel do veículo`;
  const fipe = sum(ls, l => l.fipe || 0), idades = ls.map(idadeVeic).filter(x => x != null);
  $("fmSum").innerHTML = `<span><b>${ls.length}</b> veículo(s)</span><span>FIPE <b>${brl(fipe)}</b></span>` +
    `<span>idade média <b>${idades.length ? nf(sum(idades) / idades.length, 1) : "–"} anos</b></span>` +
    `<span><b>${ls.filter(l => !l.rastreador).length}</b> sem rastreador</span>`;
  const fmt = (c, l) => {
    const x = l[c.k];
    if (c.k === "placa") return placaBtn(l.vi, false);
    if (c.f === "brl") return brlCheio(x);
    if (c.f === "data") return x ? fmtDA(x) : "—";
    if (c.f === "int") return x == null ? "—" : nf(x);
    if (c.f === "ano") return x ?? "—";
    return esc(x ?? "—");
  };
  $("fmTb").innerHTML = `<thead><tr>${FROTA_COLS.map(c => `<th class="${c.f && c.f !== "data" ? "n" : ""}" data-c="${c.k}">${c.t}${FS.sort[0] === c.k ? (FS.sort[1] < 0 ? " ▼" : " ▲") : ""}</th>`).join("")}</tr></thead>` +
    `<tbody>${ls.map(l => `<tr>${FROTA_COLS.map(c => `<td class="${c.f && c.f !== "data" ? "n" : ""} ${c.k === "chassi" ? "mono" : ""}">${fmt(c, l)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  $("fmTb").querySelectorAll("th").forEach(th => th.onclick = () => { FS.sort = [th.dataset.c, FS.sort[0] === th.dataset.c ? -FS.sort[1] : 1]; desenharFrota(); });
  $("fmFt").textContent = "Fonte: gold.vw_veiculo_atual (centro de custo vigente na data de referência) e gold.vw_ultima_manutencao.";
}
function fecharFrota() { $("fmScrim").classList.remove("open"); $("fmScrim").setAttribute("aria-hidden", "true"); }

/* ------------------------------ guia ------------------------------ */
function abrirGuia() { $("gdScrim").classList.add("open"); $("gdScrim").setAttribute("aria-hidden", "false"); $("gdDoc").scrollTop = 0; }
function fecharGuia() { $("gdScrim").classList.remove("open"); $("gdScrim").setAttribute("aria-hidden", "true"); }

/* ------------------------------ galeria ------------------------------ */
function galeria(id, vis) {
  $(id).innerHTML = vis.length ? vis.map(vi => {
    const v = V[vi], aberta = OS.find(o => o.veic === vi && !o.saida);
    const km = sum(USO.filter(r => r.veic === vi && diaOk(r.dia)), r => r.km);
    return `<button type="button" class="gcard" data-v="${vi}">${placaMercosul(v.placa)}
      <b>${esc(v.marca)} ${esc(v.modelo)}</b><span>${esc(v.tipo)} · ${esc(v.cor || "—")} · ${v.ano ?? "—"}</span>
      <span>${esc(ccNome(v.cc_atual))}</span>
      <span class="gst"><em>${v.rastreador ? nf(km) + " km" : "sem rastreador"}</em>${aberta ? `<i style="--c:${corEtapaOS(aberta.etapa)}">${esc(aberta.etapa)}</i>` : `<i class="ok">Operando</i>`}</span></button>`;
  }).join("") : `<div class="empty">Nenhum veículo neste filtro.</div>`;
}
