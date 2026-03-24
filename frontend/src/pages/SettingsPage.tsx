import { useCallback, useEffect, useState } from 'react';
import { PageLayout, PageHeader } from '@ansible/ansible-ui-framework';
import {
  FormGroup,
  FormSelect,
  FormSelectOption,
  Label,
} from '@patternfly/react-core';
import { listAiModels } from '../services/api';
import type { AiModelInfo } from '../types/api';

export const AI_MODEL_STORAGE_KEY = 'apme-ai-model';

export function SettingsPage() {
  const [models, setModels] = useState<AiModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState(
    () => localStorage.getItem(AI_MODEL_STORAGE_KEY) ?? '',
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listAiModels()
      .then((m) => {
        setModels(m);
        const stored = localStorage.getItem(AI_MODEL_STORAGE_KEY);
        const ids = new Set(m.map((x) => x.id));
        if (stored && ids.has(stored)) {
          setSelectedModel(stored);
        } else {
          const first = m[0];
          const fallback = first?.id ?? '';
          setSelectedModel(fallback);
          if (fallback) {
            localStorage.setItem(AI_MODEL_STORAGE_KEY, fallback);
          } else {
            localStorage.removeItem(AI_MODEL_STORAGE_KEY);
          }
        }
      })
      .catch(() => setModels([]))
      .finally(() => setLoading(false));
  }, []);

  const handleChange = useCallback((value: string) => {
    setSelectedModel(value);
    if (value) {
      localStorage.setItem(AI_MODEL_STORAGE_KEY, value);
    } else {
      localStorage.removeItem(AI_MODEL_STORAGE_KEY);
    }
  }, []);

  const current = models.find((m) => m.id === selectedModel);

  return (
    <PageLayout>
      <PageHeader title="Settings" />

      <div style={{ padding: '0 24px 24px', maxWidth: 640 }}>
        <h3 style={{ marginBottom: 16 }}>AI Configuration</h3>

        <FormGroup label="Default AI model" fieldId="ai-model">
          {loading ? (
            <div style={{ opacity: 0.6 }}>Loading models...</div>
          ) : models.length === 0 ? (
            <div style={{ opacity: 0.6 }}>
              No models available. Ensure the Abbenay AI service is running and
              configured with at least one model.
            </div>
          ) : (
            <>
              <FormSelect
                id="ai-model"
                value={selectedModel}
                onChange={(_e, v) => handleChange(v)}
                aria-label="Select AI model"
              >
                {models.map((m) => (
                  <FormSelectOption
                    key={m.id}
                    value={m.id}
                    label={`${m.id} (${m.provider})`}
                  />
                ))}
              </FormSelect>

              {current && (
                <div style={{ marginTop: 8 }}>
                  <Label color="blue" isCompact>
                    {current.provider}
                  </Label>{' '}
                  <span style={{ opacity: 0.7, fontSize: 13 }}>
                    {current.name}
                  </span>
                </div>
              )}
            </>
          )}
        </FormGroup>

        <p style={{ marginTop: 24, opacity: 0.6, fontSize: 13 }}>
          The selected model is used for AI-assisted remediation (Tier 2) when
          starting a new scan with AI enabled. This preference is stored in your
          browser.
        </p>
      </div>
    </PageLayout>
  );
}
