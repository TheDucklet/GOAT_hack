import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { insightNotice } from '../api/insight-contract';
import { InsightNotice } from './InsightNotice';

it('always renders the application notice without model content', () => {
  render(<InsightNotice />);
  expect(screen.getByRole('note')).toHaveTextContent(insightNotice.disclaimer);
  expect(screen.getByRole('note')).toHaveAttribute('data-policy-version', 'notice_v1');
});
