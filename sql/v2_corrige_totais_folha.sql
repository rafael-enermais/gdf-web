-- SQL-22 (v0.21.1) - preenche o total de proventos/descontos dos recibos que ficaram em branco (aviso: NAO apaga nada)
-- Causa: recibo de aniversariante traz "Parabens ! Feliz Aniversario" na mesma linha do "Total"; o leitor antigo nao reconhecia a linha.
-- Regra: so' mexe em recibo com total em branco; o valor vem da soma dos eventos do proprio recibo (mesma importacao, empresa e cadastro).
-- Confere no final: proventos - descontos = liquido do recibo (tolerancia 2 centavos).
UPDATE gdf.pnl_folha_recibo r
   SET total_proventos = COALESCE(r.total_proventos, s.prov),
       total_descontos = COALESCE(r.total_descontos, s.desc_)
  FROM (SELECT importacao_id, empresa, cadastro, round(sum(COALESCE(provento,0)),2) AS prov, round(sum(COALESCE(desconto,0)),2) AS desc_
          FROM gdf.pnl_folha_evento GROUP BY importacao_id, empresa, cadastro) s
 WHERE s.importacao_id = r.importacao_id AND s.empresa = r.empresa AND s.cadastro = r.cadastro
   AND (r.total_proventos IS NULL OR r.total_descontos IS NULL);

-- conferencia (esperado: 0 recibos em branco; 0 recibos que nao fecham com o liquido)
SELECT count(*) FILTER (WHERE total_proventos IS NULL OR total_descontos IS NULL) AS em_branco,
       count(*) FILTER (WHERE liquido IS NOT NULL AND abs(total_proventos - total_descontos - liquido) > 0.02) AS nao_fecham,
       round(sum(total_proventos),2) AS proventos_total
  FROM gdf.pnl_folha_recibo r JOIN gdf.pnl_importacao i ON i.id = r.importacao_id WHERE i.ativo;
