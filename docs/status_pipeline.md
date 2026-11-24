# Status do pipeline

- **Última execução:** 24/11/2026 02:27 (horário de Fortaleza)
- **Resultado:** ✅ sucesso
- **Simulação até:** 23/11/2026
- **Duração:** 212 s (gerar 83 s, bronze 92 s, frota 1 s, telemetria 8 s, manutencao 3 s, gold 13 s, testes 3 s, retencao 1 s, resumo 2 s, dashboard 5 s)

| Indicador | Valor |
| --- | --- |
| Período dos dados | 01/05/2026 a 23/11/2026 |
| Viagens (gold) | 97.922 |
| Alertas (gold) | 75.716 |
| Ordens de serviço (gold) | 199 |
| Outliers aguardando revisão | 32 |
| OS em quarentena | 3 |
| Tamanho do banco | 250 MB |

## Testes de qualidade

```
Relatório de qualidade — 24/11/2026 05:27:13

[OK    ] gold   | fato_alertas = silver.alertas menos a regra do motor ocioso
[OK    ] gold   | fato_utilizacao = silver.viagens
[OK    ] gold   | fato_manutencao = silver.os_manutencao
[OK    ] silver | alertas/viagens com placa fora da dim_veiculo
[OK    ] silver | OS com placa fora da dim_veiculo (deveriam estar na quarentena)
[OK    ] bronze | lotes carregados e ainda não tratados
[OK    ] gold   | viagem com velocidade média implícita > 200 km/h
[OK    ] gold   | fato sem centro de custo (veículo sem alocação na data)
[OK    ] gold   | OS com datas do fluxo fora de ordem
[OK    ] gold   | OS com valor negociado acima do orçamento
[AVISO ] gold   | OS com veículo substituto sem placa do substituto -> 3
[OK    ] gold   | OS com status digitado diferente da etapa pelas datas
[OK    ] gold   | veículo ativo sem alocação vigente
[AVISO ] silver | outliers aguardando revisão (Pendente) -> 32
[AVISO ] silver | OS em quarentena -> 3

Contagens:
  bronze: 107
  silver.alertas: 81.556
  silver.viagens: 97.922
  silver.os_manutencao: 199
  gold.fato_alertas: 75.716
  gold.fato_utilizacao: 97.922
  gold.fato_manutencao: 199

15 testes | 12 OK | 3 aviso(s) | 0 crítico(s) falhando
```
