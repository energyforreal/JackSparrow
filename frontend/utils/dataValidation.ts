/**
 * Frontend data validation utilities.
 *
 * Provides utilities to validate data structures received from backend,
 * compare expected vs actual data, and report mismatches.
 */

import { logWebSocketMessage } from './communicationLogger';

export interface DataMismatch {
  fieldPath: string;
  expectedValue: any;
  actualValue: any;
  mismatchType: 'type' | 'value' | 'missing' | 'extra' | 'structure';
  description: string;
}

export interface ValidationResult {
  isValid: boolean;
  mismatches: DataMismatch[];
  validatedAt: string;
}

export class DataValidator {
  private mismatches: DataMismatch[] = [];
  private strictMode: boolean;

  constructor(strictMode: boolean = false) {
    this.strictMode = strictMode;
  }

  /**
   * Validate data structure against expected schema
   */
  validateStructure(
    data: any,
    expectedSchema: any,
    path: string = ''
  ): DataMismatch[] {
    const mismatches: DataMismatch[] = [];

    if (expectedSchema.type === 'object') {
      mismatches.push(...this.validateObjectStructure(data, expectedSchema, path));
    } else if (expectedSchema.type === 'array') {
      mismatches.push(...this.validateArrayStructure(data, expectedSchema, path));
    } else {
      mismatches.push(...this.validatePrimitive(data, expectedSchema, path));
    }

    // Check required fields
    if (expectedSchema.required && (data === null || data === undefined)) {
      mismatches.push({
        fieldPath: path,
        expectedValue: 'non-null value',
        actualValue: null,
        mismatchType: 'missing',
        description: 'Required field is null or missing'
      });
    }

    this.mismatches.push(...mismatches);
    return mismatches;
  }

  private validateObjectStructure(
    data: any,
    schema: any,
    path: string
  ): DataMismatch[] {
    const mismatches: DataMismatch[] = [];

    if (typeof data !== 'object' || data === null || Array.isArray(data)) {
      return [{
        fieldPath: path,
        expectedValue: 'object',
        actualValue: this.getTypeName(data),
        mismatchType: 'type',
        description: 'Expected object but got different type'
      }];
    }

    const expectedProperties = schema.properties || {};

    // Check for missing required properties
    const requiredProps = schema.required || [];
    for (const prop of requiredProps) {
      if (!(prop in data)) {
        mismatches.push({
          fieldPath: path ? `${path}.${prop}` : prop,
          expectedValue: 'present',
          actualValue: 'missing',
          mismatchType: 'missing',
          description: `Required property '${prop}' is missing`
        });
      }
    }

    // Check existing properties
    for (const [prop, propSchema] of Object.entries(expectedProperties)) {
      const propPath = path ? `${path}.${prop}` : prop;
      if (prop in data) {
        mismatches.push(...this.validateStructure(data[prop], propSchema, propPath));
      } else if ((propSchema as any).required) {
        mismatches.push({
          fieldPath: propPath,
          expectedValue: 'present',
          actualValue: 'missing',
          mismatchType: 'missing',
          description: `Required property '${prop}' is missing`
        });
      }
    }

    // Check for extra properties if schema is strict
    if (schema.additionalProperties === false) {
      const allowedProps = new Set(Object.keys(expectedProperties));
      const actualProps = new Set(Object.keys(data));
      const extraProps = Array.from(actualProps).filter(prop => !allowedProps.has(prop));

      for (const extraProp of extraProps) {
        const propPath = path ? `${path}.${extraProp}` : extraProp;
        mismatches.push({
          fieldPath: propPath,
          expectedValue: 'not present',
          actualValue: data[extraProp],
          mismatchType: 'extra',
          description: `Extra property '${extraProp}' not allowed by schema`
        });
      }
    }

    return mismatches;
  }

  private validateArrayStructure(
    data: any,
    schema: any,
    path: string
  ): DataMismatch[] {
    const mismatches: DataMismatch[] = [];

    if (!Array.isArray(data)) {
      return [{
        fieldPath: path,
        expectedValue: 'array',
        actualValue: this.getTypeName(data),
        mismatchType: 'type',
        description: 'Expected array but got different type'
      }];
    }

    const itemSchema = schema.items;

    // Validate array length constraints
    const minItems = schema.minItems;
    const maxItems = schema.maxItems;

    if (minItems !== undefined && data.length < minItems) {
      mismatches.push({
        fieldPath: path,
        expectedValue: `at least ${minItems} items`,
        actualValue: data.length,
        mismatchType: 'value',
        description: `Array has ${data.length} items but minimum is ${minItems}`
      });
    }

    if (maxItems !== undefined && data.length > maxItems) {
      mismatches.push({
        fieldPath: path,
        expectedValue: `at most ${maxItems} items`,
        actualValue: data.length,
        mismatchType: 'value',
        description: `Array has ${data.length} items but maximum is ${maxItems}`
      });
    }

    // Validate each item
    if (itemSchema) {
      data.forEach((item, index) => {
        const itemPath = `${path}[${index}]`;
        mismatches.push(...this.validateStructure(item, itemSchema, itemPath));
      });
    }

    return mismatches;
  }

  private validatePrimitive(
    data: any,
    schema: any,
    path: string
  ): DataMismatch[] {
    const mismatches: DataMismatch[] = [];

    const expectedType = schema.type;
    if (expectedType) {
      const actualType = this.getJsonType(data);

      // Allow numeric types to be flexible
      if (expectedType === 'number') {
        if (actualType !== 'number' && actualType !== 'integer' && actualType !== 'float') {
          mismatches.push({
            fieldPath: path,
            expectedValue: expectedType,
            actualValue: actualType,
            mismatchType: 'type',
            description: `Expected ${expectedType} but got ${actualType}`
          });
        }
      } else if (expectedType !== actualType) {
        mismatches.push({
          fieldPath: path,
          expectedValue: expectedType,
          actualValue: actualType,
          mismatchType: 'type',
          description: `Expected ${expectedType} but got ${actualType}`
        });
      }
    }

    // Validate enum values
    const enumValues = schema.enum;
    if (enumValues && !enumValues.includes(data)) {
      mismatches.push({
        fieldPath: path,
        expectedValue: enumValues,
        actualValue: data,
        mismatchType: 'value',
        description: `Value ${data} not in allowed enum values ${enumValues}`
      });
    }

    return mismatches;
  }

  private getJsonType(value: any): string {
    if (value === null) return 'null';
    if (typeof value === 'boolean') return 'boolean';
    if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number';
    if (typeof value === 'string') return 'string';
    if (Array.isArray(value)) return 'array';
    if (typeof value === 'object') return 'object';
    return typeof value;
  }

  private getTypeName(value: any): string {
    if (value === null) return 'null';
    if (Array.isArray(value)) return 'array';
    return typeof value;
  }

  /**
   * Compare expected vs actual data for equality
   */
  compareData(
    expected: any,
    actual: any,
    path: string = '',
    tolerance: number = 0
  ): DataMismatch[] {
    const mismatches: DataMismatch[] = [];

    // Handle null values
    if (expected === null && actual === null) return mismatches;
    if (expected === null || actual === null) {
      return [{
        fieldPath: path,
        expectedValue: expected,
        actualValue: actual,
        mismatchType: 'value',
        description: 'One value is null, other is not'
      }];
    }

    // Handle different types
    if (typeof expected !== typeof actual) {
      // Special case: allow number/string interchange for numeric values
      if (typeof expected === 'number' && typeof actual === 'string') {
        const parsed = parseFloat(actual);
        if (!isNaN(parsed)) {
          return this.compareData(expected, parsed, path, tolerance);
        }
      }
      return [{
        fieldPath: path,
        expectedValue: typeof expected,
        actualValue: typeof actual,
        mismatchType: 'type',
        description: 'Types do not match'
      }];
    }

    // Compare based on type
    if (typeof expected === 'object') {
      if (Array.isArray(expected)) {
        mismatches.push(...this.compareArrays(expected, actual, path, tolerance));
      } else {
        mismatches.push(...this.compareObjects(expected, actual, path, tolerance));
      }
    } else if (typeof expected === 'number') {
      if (Math.abs(expected - actual) > tolerance) {
        mismatches.push({
          fieldPath: path,
          expectedValue: expected,
          actualValue: actual,
          mismatchType: 'value',
          description: `Numeric values differ (tolerance: ${tolerance})`
        });
      }
    } else if (expected !== actual) {
      mismatches.push({
        fieldPath: path,
        expectedValue: expected,
        actualValue: actual,
        mismatchType: 'value',
        description: 'Values are not equal'
      });
    }

    this.mismatches.push(...mismatches);
    return mismatches;
  }

  private compareObjects(
    expected: Record<string, any>,
    actual: Record<string, any>,
    path: string,
    tolerance: number
  ): DataMismatch[] {
    const mismatches: DataMismatch[] = [];

    const expectedKeys = new Set(Object.keys(expected));
    const actualKeys = new Set(Object.keys(actual));

    // Check for missing keys
    const missingKeys = Array.from(expectedKeys).filter(key => !actualKeys.has(key));
    for (const key of missingKeys) {
      mismatches.push({
        fieldPath: path ? `${path}.${key}` : key,
        expectedValue: expected[key],
        actualValue: 'missing',
        mismatchType: 'missing',
        description: `Expected key '${key}' is missing`
      });
    }

    // Check for extra keys
    const extraKeys = Array.from(actualKeys).filter(key => !expectedKeys.has(key));
    for (const key of extraKeys) {
      mismatches.push({
        fieldPath: path ? `${path}.${key}` : key,
        expectedValue: 'not expected',
        actualValue: actual[key],
        mismatchType: 'extra',
        description: `Unexpected key '${key}' found`
      });
    }

    // Compare common keys
    for (const key of Array.from(expectedKeys).filter(key => actualKeys.has(key))) {
      const keyPath = path ? `${path}.${key}` : key;
      mismatches.push(...this.compareData(expected[key], actual[key], keyPath, tolerance));
    }

    return mismatches;
  }

  private compareArrays(
    expected: any[],
    actual: any[],
    path: string,
    tolerance: number
  ): DataMismatch[] {
    const mismatches: DataMismatch[] = [];

    if (expected.length !== actual.length) {
      mismatches.push({
        fieldPath: path,
        expectedValue: expected.length,
        actualValue: actual.length,
        mismatchType: 'structure',
        description: 'Array lengths do not match'
      });
      return mismatches;
    }

    for (let i = 0; i < expected.length; i++) {
      const itemPath = `${path}[${i}]`;
      mismatches.push(...this.compareData(expected[i], actual[i], itemPath, tolerance));
    }

    return mismatches;
  }

  /**
   * Log all accumulated mismatches
   */
  logMismatches(correlationId?: string, context?: Record<string, any>): void {
    if (this.mismatches.length === 0) return;

    // Log validation failure as an internal diagnostic event using outbound direction
    logWebSocketMessage(
      'outbound',
      'data_validation',
      {
        mismatchCount: this.mismatches.length,
        mismatches: this.mismatches,
        validationType: 'frontend_data_validation',
        ...context
      },
      {
        correlationId
      }
    );

    if (this.strictMode) {
      throw new Error(`Data validation failed with ${this.mismatches.length} mismatches`);
    }
  }

  /**
   * Clear accumulated mismatches
   */
  clearMismatches(): void {
    this.mismatches = [];
  }

  /**
   * Get all mismatches
   */
  getMismatches(): DataMismatch[] {
    return [...this.mismatches];
  }
}

// Global validator instances
export const defaultValidator = new DataValidator(false);
export const strictValidator = new DataValidator(true);

/**
 * Validate WebSocket message structure
 */
export function validateWebSocketMessage(
  message: any,
  expectedSchema?: any,
  correlationId?: string
): ValidationResult {
  const validator = new DataValidator();

  // Basic WebSocket envelope validation
  const envelopeSchema = {
    type: 'object',
    properties: {
      type: { type: 'string', required: true },
      resource: { type: 'string' },
      data: { type: 'object' },
      timestamp: { type: 'string' },
      correlation_id: { type: 'string' },
      request_id: { type: 'string' }
    }
  };

  let mismatches = validator.validateStructure(message, envelopeSchema);

  // Validate message-specific schema if provided
  if (expectedSchema && message.data) {
    mismatches = mismatches.concat(validator.validateStructure(message.data, expectedSchema, 'data'));
  }

  validator.logMismatches(correlationId, { validationType: 'websocket_message' });

  return {
    isValid: mismatches.length === 0,
    mismatches,
    validatedAt: new Date().toISOString()
  };
}

/**
 * Compare backend data with frontend received data
 */
export function compareBackendFrontendData(
  backendData: any,
  frontendReceivedData: any,
  dataType: string,
  correlationId?: string,
  tolerance: number = 0.001
): ValidationResult {
  const validator = new DataValidator();

  const mismatches = validator.compareData(backendData, frontendReceivedData, '', tolerance);

  if (mismatches.length > 0) {
    validator.logMismatches(correlationId, {
      validationType: 'backend_frontend_comparison',
      dataType,
      backendDataSummary: {
        type: typeof backendData,
        size: JSON.stringify(backendData || '').length
      },
      frontendDataSummary: {
        type: typeof frontendReceivedData,
        size: JSON.stringify(frontendReceivedData || '').length
      }
    });
  }

  return {
    isValid: mismatches.length === 0,
    mismatches,
    validatedAt: new Date().toISOString()
  };
}

/**
 * Validate common message types
 */
export const messageSchemas = {
  signal: {
    type: 'object',
    properties: {
      signal: { type: 'string', enum: ['STRONG_BUY', 'BUY', 'HOLD', 'SELL', 'STRONG_SELL'] },
      confidence: { type: 'number', required: true },
      reasoning_chain: { type: 'object' },
      model_predictions: { type: 'array' },
      model_consensus: { type: 'array' },
      individual_model_reasoning: { type: 'array' },
      timestamp: { type: 'string', required: true }
    }
  },

  portfolio: {
    type: 'object',
    properties: {
      total_value: { type: 'number', required: true },
      available_balance: { type: 'number', required: true },
      positions: { type: 'array' },
      timestamp: { type: 'string' }
    }
  },

  trade: {
    type: 'object',
    properties: {
      order_id: { type: 'string', required: true },
      symbol: { type: 'string', required: true },
      side: { type: 'string', enum: ['buy', 'sell'], required: true },
      quantity: { type: 'number', required: true },
      price: { type: 'number', required: true },
      timestamp: { type: 'string', required: true }
    }
  }
};