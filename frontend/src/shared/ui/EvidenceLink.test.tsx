import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HttpClient } from '../api/http';
import { normalizeError } from '../api/errors';
import type { Evidence } from '../api/types';

vi.mock('../api/index', () => ({ http: new HttpClient('https://api.example.test/api/', async () => { throw new Error('Unexpected request'); }) }));
import { evidenceApi } from '../api/evidence';
import { EvidenceLink } from './EvidenceLink';

const bank: Evidence = { id: 'bank-id', kind: 'bank', source_id: 'doc-id', version: 'pdf-v1', excerpt: 'Учебный материал <img src=x onerror=alert(1)>', locator: { page: 3, document_date: '2024-06-01', url: 'https://evil.test/not-our-pdf' } };
beforeEach(() => { vi.spyOn(evidenceApi, 'source').mockResolvedValue(bank); });
describe('authorized EvidenceLink', () => {
  it('resolves lazily and constructs a protected PDF link with the configured API base and exact page', async () => {
    render(<EvidenceLink id="bank-id" />);
    expect(evidenceApi.source).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Основание'));
    const pdf = await screen.findByRole('link', { name: 'Открыть защищённый PDF · страница 3 ↗' });
    expect(pdf).toHaveAttribute('href', 'https://api.example.test/api/sources/bank-id/file#page=3');
    expect(pdf).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText(/Дата документа: 2024-06-01/)).toBeVisible();
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('a[href^="https://evil.test"]')).toBeNull();
  });
  it('shows the exact profile field, value and stale warning from the authorized response', async () => {
    vi.mocked(evidenceApi.source).mockResolvedValue({ ...bank, kind: 'company', locator: { feature_path: 'features.MAINOKVED_CODE', value: '25.61', stale: true } });
    render(<EvidenceLink id="bank-id" />); fireEvent.click(screen.getByText('Основание'));
    expect(await screen.findByText('features.MAINOKVED_CODE')).toBeVisible();
    expect(screen.getByText('Значение: 25.61')).toBeVisible();
    expect(screen.getByText(/Признак из прежней версии/)).toBeVisible();
  });
  it('does not show private content on 403 or invent a PDF URL when the page is absent', async () => {
    vi.mocked(evidenceApi.source).mockRejectedValue(normalizeError(403, {}));
    render(<EvidenceLink id="bank-id" />); fireEvent.click(screen.getByText('Основание'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа');
    expect(screen.queryByText(bank.excerpt)).not.toBeInTheDocument();
    vi.mocked(evidenceApi.source).mockResolvedValue({ ...bank, locator: {} });
    fireEvent.click(screen.getByText('Повторить'));
    expect(await screen.findByText(/Страница не указана/)).toBeVisible();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
  it('rejects executable news links and ignores a late response after closing the source', async () => {
    vi.mocked(evidenceApi.source).mockResolvedValue({ ...bank, kind: 'news', locator: { url: 'javascript:alert(1)' } });
    render(<EvidenceLink id="bank-id" />); fireEvent.click(screen.getByText('Основание'));
    expect(await screen.findByText(/Безопасная ссылка/)).toBeVisible();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Основание'));
    let resolve!: (value: Evidence) => void;
    vi.mocked(evidenceApi.source).mockReturnValue(new Promise((done) => { resolve = done; }));
    fireEvent.click(screen.getByText('Основание'));
    const signal = vi.mocked(evidenceApi.source).mock.calls.at(-1)![1]!;
    fireEvent.click(screen.getByText('Основание')); expect(signal.aborted).toBe(true);
    await act(async () => resolve(bank));
    expect(screen.queryByText(bank.excerpt)).not.toBeInTheDocument();
  });
});
