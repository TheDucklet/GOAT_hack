import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { describe, expect, it } from 'vitest';
import openapi from '../../../docs/contracts/openapi.json';
import examples from '../../../docs/contracts/examples.json';
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
