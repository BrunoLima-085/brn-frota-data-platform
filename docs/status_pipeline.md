# Status do pipeline

- **Última execução:** 22/11/2026 19:55 (horário de Fortaleza)
- **Resultado:** ✅ sucesso
- **Simulação até:** 21/11/2026
- **Duração:** 201 s (gerar 70 s, bronze 95 s, frota 2 s, telemetria 3 s, manutencao 2 s, gold 13 s, testes 4 s, retencao 2 s, resumo 3 s, dashboard 7 s)

| Indicador | Valor |
| --- | --- |
| Período dos dados | 01/05/2026 a 21/11/2026 |
| Viagens (gold) | 97.150 |
| Alertas (gold) | 75.187 |
| Ordens de serviço (gold) | 197 |
| Outliers aguardando revisão | 32 |
| OS em quarentena | 3 |
| Tamanho do banco | 248 MB |

## Testes de qualidade

```
Relatório de qualidade — 22/11/2026 22:55:10

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
  bronze: 101
  silver.alertas: 80.986
  silver.viagens: 97.150
  silver.os_manutencao: 197
  gold.fato_alertas: 75.187
  gold.fato_utilizacao: 97.150
  gold.fato_manutencao: 197

15 testes | 12 OK | 3 aviso(s) | 0 crítico(s) falhando
```
