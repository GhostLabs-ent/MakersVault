import assert from "node:assert/strict";

// Called only by the functional picker fixture, never inside a timed workflow.
export async function checkSidebarMenus({ page, session, check, acceptNextFolderDelete }) {
  async function request(path, method, body) {
    const response = await session.fetch(path, { method, headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body) });
    assert.equal(response.status, 200, `${method} ${path}`);
    return response.json();
  }
  const parent = await request('/folders', 'POST', { name: 'Menu parent A' });
  const sibling = await request('/folders', 'POST', { name: 'Menu parent B' });
  const leaf = await request('/folders', 'POST', { name: 'Shared leaf', parent_id: parent.id });
  const otherLeaf = await request('/folders', 'POST', { name: 'Shared leaf', parent_id: sibling.id });
  await page.reload();
  const sidebar = page.locator('aside');
  const row = name => sidebar.getByTitle(name, { exact: true }).locator('..');
  const menu = name => row(name).locator('details');
  const trigger = name => menu(name).locator('summary');
  const actions = name => menu(name).locator('.sidebar-folder-menu');
  const waitClosed = async name => {
    await actions(name).waitFor({ state: 'detached' });
    assert.equal(await menu(name).evaluate(element => element.open), false);
  };
  await row('Menu parent A / Shared leaf').waitFor();
  await row('Menu parent B / Shared leaf').waitFor();
  assert.equal(await sidebar.locator('.sidebar-folder-menu').count(), 0);
  await trigger('Menu parent A').focus();
  await trigger('Menu parent A').press('Enter');
  await actions('Menu parent A').waitFor();
  assert.deepEqual(await actions('Menu parent A').getByRole('button').allTextContents(),
    [' Subfolder', ' Rename & edit', ' Download ZIP', ' Delete']);
  await trigger('Menu parent A').press('Tab');
  assert.equal(await actions('Menu parent A').getByRole('button', { name: 'Subfolder', exact: true })
    .evaluate(element => element === document.activeElement), true);
  await page.keyboard.press('Escape');
  await waitClosed('Menu parent A');
  assert.equal(await trigger('Menu parent A').evaluate(element => element === document.activeElement), true);
  await trigger('Menu parent A').press('Space');
  await actions('Menu parent A').waitFor();
  await trigger('Menu parent A').press('Space');
  await waitClosed('Menu parent A');
  // Explicitly injected coalesced native-toggle race, not normal user automation.
  await menu('Menu parent A').evaluate(element => { element.open = true; element.open = false; element.open = true; });
  await actions('Menu parent A').waitFor();
  await trigger('Menu parent A').click(); await waitClosed('Menu parent A');
  await check('sidebar menus mount only on open; native Enter/Space, Tab, Escape/focus and coalesced toggle/reopen preserve action order');

  const leftPath = 'Menu parent A / Shared leaf', rightPath = 'Menu parent B / Shared leaf';
  await trigger(leftPath).click();
  await actions(leftPath).getByRole('button', { name: 'Rename & edit', exact: true }).click();
  await waitClosed(leftPath);
  const edit = sidebar.getByRole('dialog', { name: 'Edit folder', exact: true });
  await edit.getByLabel('Name', { exact: true }).fill('Renamed leaf');
  const [renamed] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === `/api/folder/${leaf.id}` && response.request().method() === 'PATCH'),
    edit.getByRole('button', { name: 'Save changes', exact: true }).click(),
  ]);
  assert.equal(renamed.status(), 200); await edit.waitFor({ state: 'detached' });
  await row('Menu parent A / Renamed leaf').waitFor();
  await row(rightPath).waitFor();
  const folders = await request('/folders', 'GET');
  assert.equal(folders.find(folder => folder.id === leaf.id).name, 'Renamed leaf');
  assert.equal(folders.find(folder => folder.id === otherLeaf.id).name, 'Shared leaf');
  await check('duplicate leaf labels retain exact folder ownership through rename and refresh');

  // Keep one menu open while another real UI action refreshes the folder objects.
  await trigger('Menu parent A').click(); await actions('Menu parent A').waitFor();
  await request(`/folder/${parent.id}`, 'PATCH', { name: 'Menu parent A refreshed', tags: [] });
  await trigger('Menu parent B').click();
  await actions('Menu parent B').getByRole('button', { name: 'Subfolder', exact: true }).click();
  const create = sidebar.getByRole('dialog', { name: 'Create folder', exact: true });
  assert.equal(await create.getByRole('combobox').inputValue(), sibling.id);
  await create.getByLabel('Name', { exact: true }).fill('UI child');
  await create.getByRole('button', { name: 'Create', exact: true }).click();
  await create.waitFor({ state: 'detached' });
  await row('Menu parent B / UI child').waitFor();
  await actions('Menu parent A refreshed').waitFor();
  assert.equal(await sidebar.locator('.sidebar-folder-menu').count(), 1);
  assert.equal((await request('/folders', 'GET')).find(folder => folder.name === 'UI child').parent_id, sibling.id);
  await check('subfolder targets the owning parent; another open menu follows refreshed folder data without opening closed siblings');

  // Synthetic browser DataTransfer exercises the existing file-drop handlers, not OS drag support.
  const droppedBytes = 'cube([7,8,9]);\n';
  const transfer = await page.evaluateHandle(bytes => {
    const data = new DataTransfer(); data.items.add(new File([bytes], 'menu-drop.scad', { type: 'text/plain' })); return data;
  }, droppedBytes);
  const dropRow = row('Menu parent A refreshed');
  await dropRow.dispatchEvent('dragover', { dataTransfer: transfer });
  assert.match(await dropRow.getAttribute('class'), /is-drop-target/);
  const [uploadedResponse] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/upload' && response.request().method() === 'POST'),
    dropRow.dispatchEvent('drop', { dataTransfer: transfer }),
  ]);
  await transfer.dispose(); assert.equal(uploadedResponse.status(), 200);
  const uploaded = await uploadedResponse.json();
  assert.equal(uploaded.folder_id, parent.id);
  assert.equal(await (await session.fetch(uploaded.url)).text(), droppedBytes);
  await actions('Menu parent A refreshed').waitFor();
  const [download, response] = await Promise.all([
    page.waitForEvent('download'),
    page.waitForResponse(response => new URL(response.url()).pathname === `/api/folder/${parent.id}/download`),
    actions('Menu parent A refreshed').getByRole('button', { name: 'Download ZIP', exact: true }).click(),
  ]);
  assert.equal(response.status(), 200); assert.equal(await download.failure(), null);
  assert.match(download.suggestedFilename(), /Menu_parent_A_refreshed.*\.zip$/);
  await waitClosed('Menu parent A refreshed');
  await check('folder drop keeps exact target and original bytes; refreshed-name ZIP download uses the current folder and closes its menu');

  await trigger(rightPath).click();
  await actions(rightPath).getByRole('button', { name: 'Delete', exact: true }).click(); // Default fixture handler dismisses confirmation.
  await waitClosed(rightPath); await row(rightPath).waitFor();
  assert.ok((await request('/folders', 'GET')).some(folder => folder.id === otherLeaf.id));
  await trigger(rightPath).click();
  acceptNextFolderDelete();
  const [removed] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === `/api/folder/${otherLeaf.id}` && response.request().method() === 'DELETE'),
    actions(rightPath).getByRole('button', { name: 'Delete', exact: true }).click(),
  ]);
  assert.equal(removed.status(), 200); await row(rightPath).waitFor({ state: 'detached' });
  assert.equal(await sidebar.locator('.sidebar-folder-menu').count(), 0);
  assert.ok((await request('/folders', 'GET')).some(folder => folder.id === leaf.id));
  await check('cancelled deletion preserves the folder; confirmed deletion removes only the intended duplicate leaf and its menu');

  await trigger('Menu parent A refreshed / Renamed leaf').click();
  await actions('Menu parent A refreshed / Renamed leaf').waitFor();
  await row('Menu parent A refreshed').getByRole('button', { name: 'Collapse', exact: true }).click();
  await row('Menu parent A refreshed / Renamed leaf').waitFor({ state: 'detached' });
  await row('Menu parent A refreshed').getByRole('button', { name: 'Expand', exact: true }).click();
  await waitClosed('Menu parent A refreshed / Renamed leaf');
  await trigger('Menu parent A refreshed / Renamed leaf').click();
  const search = sidebar.getByRole('textbox', { name: 'Search folders', exact: true });
  await search.fill('Menu parent B');
  await row('Menu parent A refreshed').waitFor({ state: 'detached' });
  await search.fill('');
  await waitClosed('Menu parent A refreshed / Renamed leaf');
  await check('collapse/filter unmount open descendant menus; expansion and clearing search return closed triggers without stale actions');

  // Remove only this helper's synthetic data, leaving the original two-card picker fixture intact.
  await request(`/asset/${uploaded.id}`, 'DELETE');
  return { parentId: parent.id, parentPath: 'Menu parent A refreshed' };
}

export async function checkViewerSidebarMenu({ page, session, folder, check }) {
  const sidebar = page.locator('aside');
  const row = sidebar.getByTitle(folder.parentPath, { exact: true }).locator('..');
  assert.equal(await sidebar.locator('.sidebar-folder-menu').count(), 0);
  await row.locator('summary').click();
  await row.locator('.sidebar-folder-menu').waitFor();
  assert.deepEqual(await row.locator('.sidebar-folder-menu').getByRole('button').allTextContents(), [' Download ZIP']);
  const denied = await session.fetch(`/folder/${folder.parentId}`, { method: 'DELETE' });
  assert.equal(denied.status, 403);
  await row.locator('summary').focus(); await page.keyboard.press('Escape');
  await row.locator('.sidebar-folder-menu').waitFor({ state: 'detached' });
  await check('real Viewer sidebar mounts only Download ZIP, retains keyboard dismissal and is independently refused folder deletion by the API');
}
