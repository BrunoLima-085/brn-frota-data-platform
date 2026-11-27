# Status do pipeline

- **Última execução:** 27/11/2026 00:45 (horário de Fortaleza)
- **Resultado:** ✅ sucesso
- **Simulação até:** 26/11/2026
- **Duração:** 200 s (gerar 55 s, bronze 96 s, frota 2 s, telemetria 11 s, manutencao 5 s, gold 15 s, testes 5 s, retencao 2 s, resumo 3 s, dashboard 7 s)

| Indicador | Valor |
| --- | --- |
| Período dos dados | 01/05/2026 a 26/11/2026 |
| Viagens (gold) | 99.603 |
| Alertas (gold) | 77.117 |
| Ordens de serviço (gold) | 204 |
| Outliers aguardando revisão | 33 |
| OS em quarentena | 3 |
| Tamanho do banco | 256 MB |

## Testes de qualidade

```
Relatório de qualidade — 27/11/2026 03:45:18

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
[AVISO ] silver | outliers aguardando revisão (Pendente) -> 33
[AVISO ] silver | OS em quarentena -> 3

Contagens:
  bronze: 116
  silver.alertas: 83.048
  silver.viagens: 99.603
  silver.os_manutencao: 204
  gold.fato_alertas: 77.117
  gold.fato_utilizacao: 99.603
  gold.fato_manutencao: 204

15 testes | 12 OK | 3 aviso(s) | 0 crítico(s) falhando
```
