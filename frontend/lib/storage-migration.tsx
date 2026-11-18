'use client';

import { useEffect } from 'react';
import { loadState, removeState, saveState, STORAGE_KEYS } from '@/lib/storage';
import type { ProfileResponse } from '@/lib/types';

export default function StorageMigration() {
  useEffect(() => {
    removeState(STORAGE_KEYS.legacyHistory);

    const profile = loadState<ProfileResponse & { raw_resume_text?: string }>(STORAGE_KEYS.profile);
    if (profile?.profile_id && profile.profile) {
      saveState(STORAGE_KEYS.profile, {
        profile_id: profile.profile_id,
        profile: profile.profile,
      } satisfies ProfileResponse);
    }
  }, []);

  return null;
}
