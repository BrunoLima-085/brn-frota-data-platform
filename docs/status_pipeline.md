# Status do pipeline

- **Última execução:** 25/11/2026 01:27 (horário de Fortaleza)
- **Resultado:** ✅ sucesso
- **Simulação até:** 24/11/2026
- **Duração:** 250 s (gerar 83 s, bronze 117 s, frota 2 s, telemetria 12 s, manutencao 5 s, gold 15 s, testes 4 s, retencao 2 s, resumo 3 s, dashboard 7 s)

| Indicador | Valor |
| --- | --- |
| Período dos dados | 01/05/2026 a 24/11/2026 |
| Viagens (gold) | 98.513 |
| Alertas (gold) | 76.226 |
| Ordens de serviço (gold) | 201 |
| Outliers aguardando revisão | 32 |
| OS em quarentena | 3 |
| Tamanho do banco | 253 MB |

## Testes de qualidade

```
Relatório de qualidade — 25/11/2026 04:27:07

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
  bronze: 110
  silver.alertas: 82.093
  silver.viagens: 98.513
  silver.os_manutencao: 201
  gold.fato_alertas: 76.226
  gold.fato_utilizacao: 98.513
  gold.fato_manutencao: 201

15 testes | 12 OK | 3 aviso(s) | 0 crítico(s) falhando
```
