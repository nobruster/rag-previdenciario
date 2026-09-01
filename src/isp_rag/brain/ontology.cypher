// Ontologia do Brain — schema ambicioso, carga incremental (spec §5.3).
// Modelada completa desde o início: migrar grafo depois é caro.
//
// Nós:     Norma · Dispositivo · Edicao · Criterio · Indicador · Ente
// Arestas: REVOGA · ALTERA · REGULAMENTA · FUNDAMENTA · COMPOE · CONSOME_CAMPO

// ---------------------------------------------------------------------------
// Constraints de unicidade
// ---------------------------------------------------------------------------
CREATE CONSTRAINT norma_id IF NOT EXISTS
  FOR (n:Norma) REQUIRE n.identificador IS UNIQUE;

CREATE CONSTRAINT dispositivo_id IF NOT EXISTS
  FOR (d:Dispositivo) REQUIRE (d.norma, d.artigo) IS UNIQUE;

CREATE CONSTRAINT edicao_ano IF NOT EXISTS
  FOR (e:Edicao) REQUIRE e.ano IS UNIQUE;

// Critério e Indicador são POR EDIÇÃO: o mesmo nome pode ter definição
// diferente entre edições, e é exatamente isso que a pergunta de demonstração
// explora. Chave composta, não só o nome.
CREATE CONSTRAINT criterio_id IF NOT EXISTS
  FOR (c:Criterio) REQUIRE (c.edicao_ano, c.nome) IS UNIQUE;

CREATE CONSTRAINT indicador_id IF NOT EXISTS
  FOR (i:Indicador) REQUIRE (i.edicao_ano, i.nome) IS UNIQUE;

CREATE CONSTRAINT ente_cnpj IF NOT EXISTS
  FOR (e:Ente) REQUIRE e.cnpj IS UNIQUE;

// ---------------------------------------------------------------------------
// Índices de busca
// ---------------------------------------------------------------------------
CREATE INDEX norma_numero IF NOT EXISTS FOR (n:Norma) ON (n.numero);
CREATE INDEX dispositivo_artigo IF NOT EXISTS FOR (d:Dispositivo) ON (d.artigo);
CREATE INDEX criterio_nome IF NOT EXISTS FOR (c:Criterio) ON (c.nome);
CREATE INDEX indicador_nome IF NOT EXISTS FOR (i:Indicador) ON (i.nome);
CREATE INDEX ente_nome IF NOT EXISTS FOR (e:Ente) ON (e.nome);

// ---------------------------------------------------------------------------
// Propriedades por nó (documentação — o Neo4j é schema-less)
// ---------------------------------------------------------------------------
// Norma       identificador, tipo, numero, ano, data, orgao, url, situacao
// Dispositivo norma, artigo, texto_ref, situacao,
//             data_inicio_vigencia, data_fim_vigencia, url
// Edicao      ano, regime_metodologico, metodologia_ref, url_fonte, n_entes
// Criterio    edicao_ano, nome, descricao
// Indicador   edicao_ano, nome, dimensao, campo_origem
// Ente        cnpj, nome, uf
//
// Semântica das arestas:
//   (Edicao)-[:COMPOE]->(Criterio)              edição tem critérios
//   (Criterio)-[:COMPOE]->(Indicador)           critério tem indicadores
//   (Norma)-[:REVOGA]->(Norma)                  v2+
//   (Norma)-[:ALTERA {dispositivo}]->(Norma)    v2+
//   (Norma)-[:REGULAMENTA]->(Edicao)            a portaria que rege a edição
//   (Dispositivo)-[:FUNDAMENTA]->(Criterio)     v2+
//   (Dispositivo)-[:CONSOME_CAMPO]->(Indicador) v2+, linhagem normativa
