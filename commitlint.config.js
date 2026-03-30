module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', [
      'feat',     // New feature
      'fix',      // Bug fix
      'docs',     // Documentation
      'style',    // Formatting (no code change)
      'refactor', // Code restructuring
      'perf',     // Performance improvement
      'test',     // Adding tests
      'chore',    // Maintenance
      'ci',       // CI/CD changes
      'revert',   // Revert a commit
    ]],
    'subject-case': [0],  // Allow any case in subject
  },
};
