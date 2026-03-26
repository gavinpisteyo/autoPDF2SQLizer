const BASE = '/api';

async function post(path: string, body: FormData | Record<string, unknown>) {
  const isForm = body instanceof FormData;
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: isForm ? undefined : { 'Content-Type': 'application/json' },
    body: isForm ? body : JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

async function get(path: string) {
  const res = await fetch(`${BASE}${path}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

// -- Schemas --
export const listSchemas = () => get('/schemas');
export const getSchema = (docType: string) => get(`/schemas/${docType}`);
export const saveSchema = (docType: string, schema: Record<string, unknown>) =>
  post(`/schemas/${docType}`, schema);

// -- Extract --
export async function extractPdf(file: File, docType: string, customSchema?: string) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('doc_type', docType);
  if (customSchema) fd.append('custom_schema', customSchema);
  return post('/extract', fd);
}

// -- Ground Truth --
export const listGroundTruth = () => get('/ground-truth');

export async function uploadGroundTruth(pdf: File, truthJson: File, docType: string) {
  const fd = new FormData();
  fd.append('pdf', pdf);
  fd.append('truth_json', truthJson);
  fd.append('doc_type', docType);
  return post('/ground-truth', fd);
}

export async function saveAsGroundTruth(sourceFile: string, docType: string, correctedJson: string) {
  const fd = new FormData();
  fd.append('source_file', sourceFile);
  fd.append('doc_type', docType);
  fd.append('corrected_json', correctedJson);
  return post('/save-as-ground-truth', fd);
}

export const cacheGroundTruth = () => post('/cache', new FormData());

// -- Evaluate --
export const runEvaluation = () => post('/evaluate', new FormData());

// -- SQL --
export async function generateSql(
  extractedJson: string, tableName: string, dialect: string,
  schemaName: string, includeDdl: boolean,
) {
  const fd = new FormData();
  fd.append('extracted_json', extractedJson);
  fd.append('table_name', tableName);
  fd.append('dialect', dialect);
  fd.append('schema_name', schemaName);
  fd.append('include_ddl', String(includeDdl));
  return post('/generate-sql', fd);
}

export async function executeSql(sql: string, connectionString: string) {
  const fd = new FormData();
  fd.append('sql', sql);
  fd.append('connection_string', connectionString);
  return post('/execute-sql', fd);
}

export async function testConnection(connectionString: string) {
  const fd = new FormData();
  fd.append('connection_string', connectionString);
  return post('/test-connection', fd);
}

// -- Schema Generation --
export async function generateSchema(description: string, docTypeKey: string) {
  const fd = new FormData();
  fd.append('description', description);
  fd.append('doc_type_key', docTypeKey);
  return post('/generate-schema', fd);
}
