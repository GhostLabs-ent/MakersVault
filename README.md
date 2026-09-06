
<img width="612" height="408" alt="makersvaultlogoneon-removebg-preview" src="https://github.com/user-attachments/assets/32e7faae-23e3-41bb-a188-376ad2fa68df" />

![Status](https://img.shields.io/badge/status-Beta%20release-brightgreen)
![Version](https://img.shields.io/badge/version-5.1.0--rc-blue)
![Docker Pulls](https://img.shields.io/docker/pulls/shotgunwilly555/makersvault-web)
![License](https://img.shields.io/github/license/VincentCinque/MakersVault)


<h1>Makers Vault</h1>
<p>Makers Vault is a home for all your 3D print files and creative images/illustrations. Tired of having basic folders on your desktop filled with 3D print files with inconsistent names? Tired of having to load a 3D print file into your slicer just to see what it is? Look no further. Create folders, tag your files, and preview them in 3D directly in your browser. Makers Vault is fully self-hostable using Docker and accessible through your web browser for ease of use and deployment.</p> <h2>Makers Vault Home Screen</h2>

<img width="1898" height="940" alt="Screenshot 2025-12-31 093628" src="https://github.com/user-attachments/assets/5d1b62d7-73ce-4dff-b1f5-001195ea2ff2" />


<h2>Tech Stack</h2>
<ul>
  <li>Frontend: React + TypeScript (Vite), Tailwind CSS, three.js, occt-import-js.</li>
  <li>Backend: FastAPI (Python), SQLModel, SQLite.</li>
  <li>Slicer Bridge: Go (custom protocol handler).</li>
  <li>Deployment: Docker, Docker Compose.</li>
</ul>

<h2>Road Map</h2>
<h4>Version 5.1</h4>
<ul>
  <li>Bounded, cached previews that cannot freeze the library.</li>
  <li>Visible bulk organization workflows and clearer folder navigation.</li>
  <li>Observable mounted-library imports.</li>
  <li>Secure deployment defaults and tested upgrade/recovery guidance.</li>
  <li>Polish for metadata, supporting files, prepared-print summaries, LightBurn, and the local bridge.</li>
</ul>
<p>The frozen Gate 5 v5.1 candidate remains at <code>f6ff55b</code>. Later local roadmap work adds Artifact history, Trash, Projects, Machines, portable vaults, shared-vault accounts, and optional passkey MFA. Its evidence and owner checkpoints are in the <a href="makervault/docs/ARCHITECTURE_RUNBOOK.md">architecture runbook</a>; it does not replace the <a href="makervault/docs/V5.1_SCOPE.md">frozen release contract</a> without release qualification.</p>
<p><strong>Current local status:</strong> Gate 13A is accepted; <a href="makervault/docs/evidence/gate-13/SUBGATE_13B_RESULTS.md">13B lifecycle evidence</a> is ready for review. Current regression, production-HTTPS upgrade/recovery/rollback and portable-import startup pass. Browser, platform and release qualification remain 13C work. Gate 12 optional services is deferred to the desktop version. Nothing here announces a new published release.</p>

<h2>Getting Started</h2>
<p>Makers Vault is deployable using Docker pull or Docker Compose:</p>
<h3>Docker Compose</h3>

```bash
cd makervault
./scripts/setup-env.sh
docker compose -f docker-compose.deploy.yml up -d
```

<p><code>makervault/docker-compose.deploy.yml</code> is the canonical production manifest. <code>makervault/docker-compose.yml</code> is the canonical local source-build manifest. The historical <code>docker-deploy.yml</code> filename is retained only as a compatibility alias.</p>
<p><strong>Security notice:</strong> production startup requires an explicit administrator password and deployment-specific signing secret. The setup helper creates both without overwriting an existing <code>.env</code>. Optional passkey MFA additionally requires one stable HTTPS RP ID and origin. Do not expose MakersVault ports directly to the public Internet.</p>
<p><strong>Existing installation:</strong> do not start new images until you have followed the tested <a href="makervault/docs/UPGRADE_V5.1.md">v5.1 upgrade procedure</a> and created a verified matched backup using the <a href="makervault/docs/BACKUP_AND_RECOVERY.md">backup and recovery guide</a>. SQLite and managed storage must always be backed up and restored together.</p>

<h3>Setting up the .env file</h3>
<p>From the <code>makervault</code> directory, generate a new <strong>.env</strong> file:</p>

```bash
./scripts/setup-env.sh
```

<p>The helper writes the canonical <code>.env.example</code> values, generates a random administrator password and 256-bit signing secret, protects the file with mode <code>600</code>, and prints the password once. For an existing installation, keep the current <code>.env</code> and follow the <a href="makervault/docs/SECURE_DEPLOYMENT.md">secure deployment and upgrade guide</a>.</p>
<p>For direct/LAN mode, set <code>VITE_API_URL</code> to a browser-reachable API URL (for example, <code>http://10.0.0.160:8000</code>). Plain HTTP is appropriate only on a genuinely trusted network because it does not protect credentials or tokens from network observers.</p>

<h3>Reverse Proxy Support (Any Provider)</h3>
<p>Makers Vault is reverse-proxy agnostic. Nginx Proxy Manager, Traefik, Nginx, Caddy, HAProxy, and Apache all work.</p>
<p><strong>Recommended single-host route:</strong></p>
<ul>
  <li>Send all paths for <code>makersvault.example</code> to <code>web:5173</code>.</li>
  <li>The web container serves the UI and proxies <code>/api/*</code> internally to <code>api:8000</code>.</li>
</ul>
<p>A second public API hostname is optional, not required. See <a href="makervault/docs/architecture/REVERSE_PROXY.md">the reverse-proxy topology guide</a>.</p>

<h4>Recommended flow for proxied setups</h4>
<p>Start containers:</p>

```bash
docker compose -f docker-compose.deploy.yml up -d
```

<ol>
  <li>Bring the stack up with Docker Compose.</li>
  <li>Configure one reverse-proxy host that sends all paths to the web service.</li>
  <li>Set <code>PUBLIC_URL</code> in <code>.env</code> (for example, <code>https://makersvault.example.com</code>) and restart.</li>
  <li>Open Makers Vault at your public domain.</li>
</ol>
<p>When served on standard proxy ports (80/443), Makers Vault automatically calls the API at <code>&lt;current-origin&gt;/api</code>.</p>

<h4>Environment values when using a reverse proxy</h4>
<ul>
  <li>Set <code>PUBLIC_URL</code> to your public domain URL.</li>
  <li>Leave <code>VITE_API_URL</code> empty unless you intentionally want a non-default API target.</li>
  <li>Set <code>CORS_ORIGINS</code> as needed for direct/LAN access or additional origins.</li>
  <li>For a separate public API hostname, set <code>TRUSTED_HOSTS</code> to that API hostname.</li>
</ul>
<p>Example:</p>

```yaml
PUBLIC_URL=https://makersvault.example.com
CORS_ORIGINS=https://makersvault.example.com,http://10.0.0.160:5173
TRUSTED_HOSTS=makersvault.example.com,10.0.0.160
VITE_API_URL=
VITE_ALLOWED_HOSTS=
```

<p><strong>Running as non-root:</strong> set <code>PUID</code> and <code>PGID</code> to your host user/group IDs (defaults to 1000). Containers create a matching user at startup so volume mounts stay writable.</p>
<p><strong>Keeping API internal:</strong> with the recommended single-host topology, the external proxy does not need an API route. You may remove the API's published host port after verifying bridge and diagnostic requirements; the web container still reaches <code>api:8000</code> on the Compose network.</p>

<h4>Quick troubleshooting</h4>
<ul>
  <li>Login fails with CORS error: add the public domain to <code>CORS_ORIGINS</code>.</li>
  <li>UI loads but API calls 404 under <code>/api</code>: forward the path unchanged to the web container and let its Nginx proxy reach the API.</li>
  <li>LetsEncrypt HTTP-01 challenge fails and returns app HTML: make sure external port 80 points to your reverse proxy (not directly to Makers Vault).</li>
  <li>Public login fails while LAN/direct works: clear/avoid hardcoded private-IP <code>VITE_API_URL</code> for proxied access.</li>
</ul>

<p>Remote access is supported through an HTTPS reverse proxy or a private network/VPN. Direct public exposure of the API or web ports is unsupported for v5.1.</p>

<h2>Project and operator documentation</h2>
<ul>
  <li><a href="makervault/docs/UPGRADE_V5.1.md">Upgrade to v5.1</a></li>
  <li><a href="makervault/docs/BACKUP_AND_RECOVERY.md">Backup and recovery</a></li>
  <li><a href="makervault/docs/SECURE_DEPLOYMENT.md">Secure deployment</a></li>
  <li><a href="makervault/docs/KNOWN_LIMITATIONS.md">Known limitations</a></li>
  <li><a href="CHANGELOG.md">Changelog</a> and <a href="makervault/docs/RELEASE_NOTES_v5.1.0.md">v5.1.0 release notes</a></li>
</ul>
<h2>Contributing</h2>
<p>Contributions are welcome. Read <a href="CONTRIBUTING.md">CONTRIBUTING.md</a> before a large change and use the issue forms for reproducible bugs or focused feature requests. Report vulnerabilities privately according to <a href="SECURITY.md">SECURITY.md</a>; do not disclose them in a public issue.</p>
<h2>Features, UI Walkthrough, and Supported File Types</h2> 
<h3>Supported File Types</h3> <p>Makers Vault supports the following file types:</p>
<h3>3D Print Files:</h3> 
<ul> 
  <li>STL</li> 
  <li>STEP</li> 
  <li>OBJ</li> 
  <li>3MF</li> 
  <li>STP</li> 
</ul> 
<h3>Image Types:</h3> 
<ul> 
  <li>SVG</li> 
  <li>PNG</li> 
  <li>JPG</li> 
  <li>WEBP</li> 
  <li>BMP</li> 
</ul> 
<h3>Other File Types</h3>
<p>Most other file types (docx, ppt, pdf, zip, etc.) are supported, but they will not render a preview. Makers Vault is mainly designed for 3D printing files, CAD, and artistic illustrations. If you need a document-focused solution, other tools may be more suitable. That said, feel free to request features if needed!</p>
<h3>Feature List</h3> 
<p>Makers Vault is intentionally kept simple to remain user-friendly while still being feature-rich for its purpose:</p> 
<ul> 
  <li>Create and delete folders.</li> 
  <li>Tag any document uploaded to Makers Vault.</li>
  <li>Sort, search, and rename documents.</li>
  <li>Add notes to documents.</li>
  <li>Toggle between light and dark mode for better viewing of differently colored 3D models.</li>
  <li>Create username and password for added security when running behind a reverse proxy.</li>
  <li>Move or delete files from within the application.</li>
  <li>Drag and drop upload.</li> 
  <li>Customization Themes.</li>
  <li>Open in Slicer (Beta).</li>
  <li>Import from link (MakerWorld, Thingiverse, and Printables).</li>
  <li>Batch tagging and batch deleting.</li>
  <li>Search at mount point for eligible file types.</li>
  <li>Robust handling of .zip imports.</li>	
</ul> 

<h2>UI and Feature Walkthrough</h2>
<p><strong>NOTE:</strong> For initial install instructions refer to the Getting Started section.</p>
<h3>Logging in for the First Time</h3> 

<img width="1906" height="932" alt="Screenshot 2025-12-31 094250" src="https://github.com/user-attachments/assets/a8804762-8ea4-4187-adc7-1312993d8d2d" />


<p>Log in using the default password set in the .env file, or a custom password if configured (recommended).</p>
<h3>Landing Page / All Items</h3> 

<img width="1913" height="941" alt="Screenshot 2025-12-31 094437" src="https://github.com/user-attachments/assets/e0fe9bb1-812e-45c5-a1dc-c0dc790b8be6" />


<h2>Uploading Files</h2>
<p>Makers Vault supports both single-file, batch uploads, and drag and drop. To upload a file, click the Upload button in the top-right corner. To upload a folder, use the Upload Folder button and select the entire folder. This action can also be performed by utilizing the drag and drop function </p> 

<img width="1912" height="936" alt="Screenshot 2025-12-31 100124" src="https://github.com/user-attachments/assets/ef14d95e-fb73-4f38-a8b9-2bbb0391c326" />


<p><strong>NOTE:</strong> Depending on the number and size of the files, upload and preview generation may take some time. Please be patient.</p> 

<h3>Uploading Single/Multiple Files</h3>

<img width="1912" height="936" alt="Screenshot 2025-12-31 100124" src="https://github.com/user-attachments/assets/fbfbea6b-0851-490d-803b-5b12fb320623" />


<h3>Dragging and Dropping to Upload</h3>
<p>Files that are dragged and dropped to upload will be placed in whatever folder is currently selected. For example: You are clicked into the folder "3D prints" and drag files into Makers Vault, it will upload to that location.</p>

<img width="1914" height="935" alt="Screenshot 2025-12-31 100230" src="https://github.com/user-attachments/assets/4a4abbbf-ee7c-4872-b6ec-306c36b6d846" />


<h3>Importing via Link (Beta)</h3>
<p>The currently supported 3D printing repository sites are:
	<ul>
		<li>MakerWorld</li>
		<li>Printables</li>
		<li>Thingiverse</li>
	</ul>
In the future there are plans to add support for more websites, but in this current release only the three listed will function. The root link from the respective repository can be used to import any models. Most models will import as a .zip file. When a zip file is imported a pop-up will appear prompting to either save as a zip or unzip and save. Unzip and save allows the user to select which files to keep and which to discard. This helps to ensure that unecessary "read-me" files aren't uploaded.
</p>

<img width="4400" height="2129" alt="Import_From_Link" src="https://github.com/user-attachments/assets/515f0e95-72e7-4ea3-81ba-3d8023f4cff3" />

<img width="1913" height="937" alt="Screenshot 2025-12-31 101451" src="https://github.com/user-attachments/assets/a397fd46-d808-46b3-b83f-d1e025be8608" />

<img width="1907" height="932" alt="Screenshot 2025-12-31 101512" src="https://github.com/user-attachments/assets/84983739-6730-4155-9027-f601c7ae7bca" />

<img width="1903" height="934" alt="Screenshot 2025-12-31 101923" src="https://github.com/user-attachments/assets/cfb322a0-f155-4b2e-b1c5-264fef84ae9c" />

<h2>Model Rendering, Tagging, and Adding Notes</h2>
<p>Makers Vault uses static 3D preview images in each tile to keep folder browsing fast. To view a fully interactive 3D preview, double-click the tile. In the pop-up window, you can rotate and inspect the 3D model interactively by clicking and holding with your mouse and dragging.</p>

<img width="1911" height="938" alt="Screenshot 2025-12-31 102102" src="https://github.com/user-attachments/assets/78b326af-d805-4054-a658-56751e9b125c" />


<p>Individual files can be renamed by double-clicking the Name field. The file extension (STL, STEP, 3MF, etc.) will be preserved even if removed by mistake.</p>

<img width="323" height="498" alt="Screenshot 2025-12-31 102311" src="https://github.com/user-attachments/assets/1fea58d9-705c-4fa0-87b0-3008a562906f" />

<h3>Tagging Files and Adding to Folders</h3> 
<p>To begin organizing files, click “New” at the top left to create a new folder. To create a sub folder click the "..." next to the newly created folder and select "+ Subfolder". </p>

<img width="4400" height="2156" alt="New_folder" src="https://github.com/user-attachments/assets/67b2fadd-ccc8-423f-af02-8778ca8b1e07" />

<img width="1907" height="932" alt="Screenshot 2025-12-31 102622" src="https://github.com/user-attachments/assets/4f87cdbe-f6d4-4276-a9dc-294b51f8eae5" />


<p>After creating a folder, assign files to it using the dropdown menu in each file tile. Alternatively, click the folder and then upload files directly — uploaded files will automatically be placed in the current folder.</p>

<img width="1910" height="930" alt="Screenshot 2025-12-31 102708" src="https://github.com/user-attachments/assets/e1eae91e-e40a-4768-b13c-fe530a1055a9" />

<img width="1909" height="935" alt="Screenshot 2025-12-31 102733" src="https://github.com/user-attachments/assets/0d46b249-45a9-4521-b6be-d69136a91f00" />

<p>When entering tags, typing a comma will close the current tag and allow you to enter the next. Example: typing “3D Print,” will create a tag named “3D Print”.</p> 

<img width="1890" height="933" alt="Screenshot 2025-12-31 102944" src="https://github.com/user-attachments/assets/418c9d71-1970-4755-808f-e5e633a27386" />

<p>To sort by tags, click the matching tag tab at the top of the page. The sorting dropdown next to the search bar allows sorting by name, size, file type, and folder (ascending or descending).</p>

<img width="1913" height="933" alt="Screenshot 2025-12-31 103028" src="https://github.com/user-attachments/assets/74ff7329-4856-4f55-8fe2-fc65846bdd42" />


<h3>Batch Tagging and Deleting</h3>
<p>The batch tagging and batch deleting feature utilizes the available select button on each individual render tile. Simply select as many models as needed and applying a tag to one will apply the tag to all selected. The same logic applies to batch deleting, any selected models will be deleted by utilizing the single delete button on any tile. </p>
<h4>Batch Tagging</h4>

<img width="1892" height="930" alt="Screenshot 2025-12-31 103532" src="https://github.com/user-attachments/assets/20b104e6-53ad-4019-b6e7-252a5e3a2cbf" />

<img width="1893" height="937" alt="Screenshot 2025-12-31 103556" src="https://github.com/user-attachments/assets/de1baffc-1baa-42ca-a705-50ac686aae0e" />

<h4>Batch Deleting</h4>

<img width="1895" height="938" alt="Screenshot 2025-12-31 103647" src="https://github.com/user-attachments/assets/7f8709f0-9a1f-4159-b48f-229fbf266c84" />

<img width="1895" height="941" alt="Screenshot 2025-12-31 103704" src="https://github.com/user-attachments/assets/68ca12f3-a52f-493a-8e0b-c3b273d43dc6" />


<h2>Open in Slicer (Beta)</h2>
<p>To utilize the open in slicer setting, first it is necessary to select the Slicer that you would like to use from Settings (near the bottom left corner) then select the sub-menu "Open in Slicer" </p>

<img width="4405" height="2189" alt="Settings" src="https://github.com/user-attachments/assets/65a173d7-5b62-4b4b-8f92-73257648b3a7" />

<img width="4400" height="2147" alt="OpeninSlicer" src="https://github.com/user-attachments/assets/38e7321b-53ef-43ad-ac96-3ceccc7c6c41" />

<p>In the Open in Slicer Settings sub-menu there are many different supported Slicers (listed in the below image). </p>

<img width="1911" height="930" alt="Screenshot 2025-12-31 105732" src="https://github.com/user-attachments/assets/653a5411-75eb-46b8-9945-2be4fbe6dcf0" />


<p>Once the appropriate slicer is selected, note that the "Open in Slicer" button on each individual 3D model render tile is updated according to the selection.</p>

<img width="317" height="485" alt="Screenshot 2025-12-31 110033" src="https://github.com/user-attachments/assets/486bde87-eb24-4ab0-b2d3-a1b56b78f114" />


<h2>Slicer Bridge</h2>
<p>For the Open in Slicer function to work, a standalone executable will need to be installed (supported for Windows and Linux). The bridge will need to be installed on any standalone machine, with the slicer installed. Example: You host Makers Vault on a Ubuntu Server but utilize the slicer on a Window's Laptop, the slicer bridge will need to be installed only once on the windows Laptop. Makers Vault is then accessed via the web browser from the Windows laptop, Open in Slicer button is clicked and the model is loaded into the Slicer of your choice.</p>

<a href="https://github.com/VincentCinque/MakersVault/tree/main/makervault/slicer-bridge">The Slicer Bridge can be downloaded here.</a>

<h2>Model Bundles</h2>
<p>Each model can include visible supporting files such as assembly PDFs, text notes, and other documentation. Expand <strong>Supporting files</strong> on a model card to add, download, or remove them. Supporting documents are included when models are downloaded as a ZIP.</p>
<p>Prepared print files are handled as internal model data rather than shown as downloadable attachments. When MakersVault finds prepared data in a 3MF or an added print file, the card shows the printer, material, nozzle size, and estimated time when those values are available. <strong>Open in Slicer</strong> hands the supplied prepared file to the configured slicer; MakersVault never slices a model, sends it to a printer, or starts a print.</p>

<h2>Settings</h2>
<p>The settings page is available from the button at the bottom-left of the app. Sub-menus include Open in Slicer, Reverse Proxy, Themes, Storage Structure, and Imports.</p>
<h3>Themes</h3>

<img width="4405" height="2189" alt="Settings" src="https://github.com/user-attachments/assets/87eb158a-d2d3-48ce-a4ec-2a6e80955c99" />


<p>The currently available themes are: System default, light, dark, neon green, neon purple, and neon blue. The themes change page accents as well as the background color.</p>

<h3>Model Previews</h3>
<p>MakersVault automatically uses embedded 3MF thumbnail artwork when available. Missing previews are generated only when their cards approach the visible area, one at a time, and are saved to the server so other browsers do not need to render them again.</p>
<p>The Model Previews setting offers <strong>Automatic</strong>, <strong>On demand</strong>, and <strong>Disabled</strong> modes. Saved or embedded thumbnails are always displayed. Interactive 3D viewing remains available when card generation is disabled.</p>

<h3>Storage Structure</h3>
<p>Managed files can be organized with a configurable path template. The default is <code>{folder}/{model}/{filename}</code>. Available tokens include <code>{folder}</code>, <code>{collection}</code>, <code>{tags}</code>, <code>{creator}</code>, <code>{model}</code>, <code>{name}</code>, <code>{filename}</code>, and <code>{id}</code>. The template must contain <code>{filename}</code> in its final path segment.</p>
<p>Model names are unique inside each MakerVault folder. Renaming a model renames the stored file while preserving its extension. Use <strong>Reorganize existing managed files now</strong> to apply a new template to the current library; mounted no-copy files are left in place.</p>

<h2>Imports Settings</h2>
<p>Makerworld enforces a 5 download only policy if not logged in. This will limit the amount of "Import from Link" requests you can make unless you place a cookie authentication token in the session cookie field in the import settings.
	
<strong> NOTE: The cookie session header is stored ONLY in the browser for security purpouses. Never share this value with anyone and avoid storing it elsewhere that can easily be accessed by someone else.</strong> </p>

<img width="1912" height="929" alt="Screenshot 2025-12-31 113127" src="https://github.com/user-attachments/assets/8a0c3f83-6fc9-41be-874d-d9b90dc86797" />


<h3>Finding the Cookie Session Header</h3>
<p><strong>Chrome / Edge</strong></p>
<ol>
  <li>Sign in to makerworld.com or thingiverse.com.</li>
  <li>Open DevTools (F12 or Ctrl+Shift+I) and go to the Network tab.</li>
  <li>Reload the page to capture requests.</li>
  <li>Click a request to the site (Type: document or fetch/xhr).</li>
  <li>In Headers -&gt; Request Headers, copy the value of <code>Cookie</code> (everything after <code>Cookie:</code>).</li>
</ol>
<p><strong>Firefox</strong></p>
<ol>
  <li>Sign in to makerworld.com or thingiverse.com.</li>
  <li>Open DevTools (F12), choose Network, and reload the page.</li>
  <li>Select a request to the site and open the Headers panel.</li>
  <li>Under Request Headers, copy the <code>Cookie</code> value (right-click -&gt; Copy Value).</li>
</ol>
<p><strong>Examples:</strong> MakerWorld cookies often include <code>mw_session</code> and <code>mw_token</code>. Thingiverse cookies often include <code>cf_clearance</code> and <code>PHPSESSID</code>.</p>
<p><strong>Tip:</strong> Cookies expire. If imports fail later, repeat these steps to refresh the cookie.</p>
