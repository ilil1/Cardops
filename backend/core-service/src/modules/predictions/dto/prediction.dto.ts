import { UnprocessableEntityException } from '@nestjs/common';

const fields = {
  customer_age: { model: 'Customer_Age', min: 26, max: 73, integer: true },
  gender: { model: 'Gender', values: ['F', 'M'] },
  dependent_count: { model: 'Dependent_count', min: 0, max: 5, integer: true },
  education_level: { model: 'Education_Level', values: ['College', 'Doctorate', 'Graduate', 'High School', 'Post-Graduate', 'Uneducated', 'Unknown'] },
  marital_status: { model: 'Marital_Status', values: ['Divorced', 'Married', 'Single', 'Unknown'] },
  income_category: { model: 'Income_Category', values: ['$120K +', '$40K - $60K', '$60K - $80K', '$80K - $120K', 'Less than $40K', 'Unknown'] },
  card_category: { model: 'Card_Category', values: ['Blue', 'Gold', 'Platinum', 'Silver'] },
  months_on_book: { model: 'Months_on_book', min: 13, max: 56, integer: true },
  total_relationship_count: { model: 'Total_Relationship_Count', min: 1, max: 6, integer: true },
  months_inactive_12_mon: { model: 'Months_Inactive_12_mon', min: 0, max: 6, integer: true },
  contacts_count_12_mon: { model: 'Contacts_Count_12_mon', min: 0, max: 6, integer: true },
  credit_limit: { model: 'Credit_Limit', min: 1438.3, max: 34516.0 },
  total_revolving_bal: { model: 'Total_Revolving_Bal', min: 0, max: 2517, integer: true },
  avg_open_to_buy: { model: 'Avg_Open_To_Buy', min: 3.0, max: 34516.0 },
  total_amt_chng_q4_q1: { model: 'Total_Amt_Chng_Q4_Q1', min: 0, max: 3.397 },
  total_trans_amt: { model: 'Total_Trans_Amt', min: 510, max: 18484, integer: true },
  total_trans_ct: { model: 'Total_Trans_Ct', min: 10, max: 139, integer: true },
  total_ct_chng_q4_q1: { model: 'Total_Ct_Chng_Q4_Q1', min: 0, max: 3.714 },
  avg_utilization_ratio: { model: 'Avg_Utilization_Ratio', min: 0, max: 0.999 },
} as const;

type Rule = { model: string; min?: number; max?: number; integer?: boolean; values?: readonly string[] };

export function validatePrediction(input: unknown): Record<string, unknown> {
  const errors: { loc: (string | number)[]; msg: string; type: string }[] = [];
  const output: Record<string, unknown> = {};
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new UnprocessableEntityException({ detail: [{ loc: ['body'], msg: 'Input should be an object', type: 'model_type' }] });
  }
  const body = input as Record<string, unknown>;
  for (const [key, rule] of Object.entries(fields) as [string, Rule][]) {
    const value = body[key];
    if (value === undefined || value === null) {
      errors.push({ loc: ['body', key], msg: 'Field required', type: 'missing' });
    } else if (rule.values) {
      if (typeof value !== 'string' || !rule.values.includes(value)) errors.push({ loc: ['body', key], msg: `Input should be ${rule.values.join(', ')}`, type: 'literal_error' });
      else output[rule.model] = value;
    } else if (typeof value !== 'number' || !Number.isFinite(value) || (rule.integer && !Number.isInteger(value))) {
      errors.push({ loc: ['body', key], msg: rule.integer ? 'Input should be a valid integer' : 'Input should be a valid number', type: rule.integer ? 'int_type' : 'float_type' });
    } else if ((rule.min !== undefined && value < rule.min) || (rule.max !== undefined && value > rule.max)) {
      errors.push({ loc: ['body', key], msg: `Input should be between ${rule.min} and ${rule.max}`, type: 'value_error' });
    } else output[rule.model] = value;
  }
  for (const key of Object.keys(body)) {
    if (!(key in fields)) errors.push({ loc: ['body', key], msg: 'Extra inputs are not permitted', type: 'extra_forbidden' });
  }
  if (errors.length) throw new UnprocessableEntityException({ detail: errors });
  return output;
}
