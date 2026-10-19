CREATE TABLE magi_chunk_sets (
 node_id text NOT NULL REFERENCES magi_nodes(id), model_id text NOT NULL REFERENCES magi_models(id),
 completed boolean NOT NULL DEFAULT false, PRIMARY KEY(node_id, model_id)
);
CREATE TABLE magi_chunks (
 id text PRIMARY KEY, node_id text NOT NULL REFERENCES magi_nodes(id), ordinal integer NOT NULL,
 rule text NOT NULL, title_path text NOT NULL, body text NOT NULL, input text NOT NULL,
 input_hash text NOT NULL, source_ranges jsonb NOT NULL
);
CREATE INDEX magi_chunks_node ON magi_chunks(node_id, ordinal);
CREATE INDEX magi_chunks_text ON magi_chunks USING gin(to_tsvector('simple', input));
CREATE TABLE magi_chunk_vectors (
 chunk_id text NOT NULL REFERENCES magi_chunks(id), model_id text NOT NULL REFERENCES magi_models(id),
 embedding vector NOT NULL, PRIMARY KEY(chunk_id, model_id)
);
CREATE INDEX magi_chunks_input_hash ON magi_chunks(input_hash);
