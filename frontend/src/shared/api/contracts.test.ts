import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { describe, expect, it } from 'vitest';
import openapi from '../../../../docs/contracts/openapi.json';
import examples from '../../../../docs/contracts/examples.json';
import insightFixtures from '../../../../docs/contracts/insight-v2-examples.json';
import insightSchema from '../../../../docs/contracts/insight.schema.json';
import envelopeSchema from '../../../../docs/contracts/insight-envelope-v2.schema.json';
import { insightNotice, isInsightV2 } from './insight-contract';
import { demoCompanies, demoInsight } from './mock/fixtures';

const validator = new Ajv2020({ strict: false, allErrors: true });
addFormats(validator);
validator.addSchema({ $id: 'backend', components: openapi.components });

describe('A-01 contract handoff', () => {
  it.each(examples.filter((example) => example.schema in openapi.components.schemas))('validates the original $name fixture against $schema', ({ schema, data }) => {
    const validate = validator.compile({ $ref: `backend#/components/schemas/${schema}` });
    expect(validate(data), JSON.stringify(validate.errors)).toBe(true);
  });

  it('identifies the one internal AI fixture outside the HTTP schema', () => {
    expect(examples.filter((example) => !(example.schema in openapi.components.schemas)).map((example) => example.name)).toEqual(['new_position']);
  });

  it('validates the composed CompanyOut and InsightOut envelopes', () => {
    for (const [schema, data] of [['CompanyOut', demoCompanies[0]], ['InsightOut', demoInsight]] as const) {
      const validate = validator.compile({ $ref: `backend#/components/schemas/${schema}` });
      expect(validate(data), JSON.stringify(validate.errors)).toBe(true);
    }
  });
});

describe('F-13 shared insight fixtures', () => {
  const validateResult = validator.compile(insightSchema);
  const validateEnvelope = validator.compile(envelopeSchema);
  const validateHttp = validator.compile({ $ref: 'backend#/components/schemas/InsightOut' });

  it.each(insightFixtures)('validates $name at AI, result and HTTP boundaries', ({ envelope }) => {
    expect(validateEnvelope(envelope), JSON.stringify(validateEnvelope.errors)).toBe(true);
    expect(validateResult(envelope.result), JSON.stringify(validateResult.errors)).toBe(true);
    expect(validateHttp({ ...demoInsight, result: envelope.result }), JSON.stringify(validateHttp.errors)).toBe(true);
    expect(envelope.result.policy_version).toBe(insightNotice.policy_version);
    expect(envelope.result.disclaimer).toBe(insightNotice.disclaimer);
  });

  it.each(examples.filter((example) => example.schema === 'InsightResult'))('keeps tagless v1: $name', ({ data }) => {
    expect(validateResult(data), JSON.stringify(validateResult.errors)).toBe(true);
  });

  it('rejects unknown versions, arbitrary actions and a replaced application notice', () => {
    const original = insightFixtures[0]!.envelope.result;
    for (const change of [
      { schema_version: 'v99' },
      { next_actions: [{ action: 'execute_tool', label: 'Run', command: 'anything' }] },
      { disclaimer: 'Model decided to remove the notice' },
    ]) {
      expect(validateResult({ ...original, ...change })).toBe(false);
    }
  });

  it('identifies legacy results for the unassessed v1 presentation', () => {
    expect(isInsightV2(demoInsight.result)).toBe(false);
    expect(() => isInsightV2(Object.assign({}, demoInsight.result, { schema_version: 'v99' }))).toThrow('Unsupported insight schema version');
  });
});
