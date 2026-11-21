const { test, expect } = require('@playwright/test');

test('first-run setup and login reaches the operator home page', async ({ page }) => {
  await page.goto('/');

  await expect(
    page.getByRole('heading', { name: 'Create the first administrator', level: 1 })
  ).toBeVisible();
  await page.locator('[data-auth-form] input[name="username"]').fill('e2e-admin');
  await page.locator('[data-auth-form] input[name="password"]').fill('e2e-a-strong-password');
  await page.getByRole('button', { name: 'Create administrator' }).click();

  await expect(page.getByText('Administrator created. Sign in to continue.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
  await page.locator('[data-auth-form] input[name="username"]').fill('e2e-admin');
  await page.locator('[data-auth-form] input[name="password"]').fill('e2e-a-strong-password');
  await page.getByRole('button', { name: 'Sign in' }).click();

  await expect(page.locator('body')).toHaveAttribute('data-auth-state', 'authenticated');
  await expect(page.getByRole('heading', { name: 'Homepage' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'World operations' })).toBeVisible();
});
